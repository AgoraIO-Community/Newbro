import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.communication import CommunicationBrain
from newbro.communication.model import CommunicationModelResult, ToolCall
from newbro.communication.tools import build_default_tool_registry
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.communication.history import InMemoryConversationHistory
from newbro.observability.emitters.communication import CommunicationDiagnosticEmitter
from newbro.observability.logger import DiagnosticLogger
from newbro.observability.store import InMemoryDiagnosticStore
from newbro.protocol import (
    InteractionRequest,
    InteractionRequestKind,
    InteractionRequestStatus,
    NotificationCandidate,
    NotificationCandidateType,
    Task,
    TaskStatus,
    TaskCommandType,
)


@pytest.mark.anyio
async def test_communication_brain_creates_task_and_returns_natural_reply():
    store = InMemoryBlackboard()
    model = ScriptedCommunicationModel(
        {
            "Help me draft an email": ScriptedPlan(
                conversational_act="acknowledge_and_start",
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        args={"title": "Draft email", "goal": "Draft an email", "mock_safe": True},
                    )
                ],
            )
        }
    )
    brain = CommunicationBrain(store, model)

    result = await brain.handle_user_message("conv-1", "Help me draft an email")

    assert result.conversational_act == "acknowledge_and_start"
    assert "successfully" not in result.reply_text.lower()
    assert len(await store.list_tasks()) == 1


class CapturingModel:
    def __init__(self) -> None:
        self.seen_histories: list[list[str]] = []

    async def respond(self, *, user_text, context, tool_registry):
        self.seen_histories.append([entry.text for entry in context.recent_history])
        return CommunicationModelResult(
            reply_text=f"reply to {user_text}",
            conversational_act="model_reply",
        )


@pytest.mark.anyio
async def test_communication_brain_replays_local_history_across_turns():
    store = InMemoryBlackboard()
    model = CapturingModel()
    brain = CommunicationBrain(store, model)

    await brain.handle_user_message("conv-1", "first")
    await brain.handle_user_message("conv-1", "second")

    assert model.seen_histories == [
        ["first"],
        ["first", "reply to first", "second"],
    ]


class FailingModel:
    async def respond(self, **kwargs):
        raise AssertionError("Model should not be called for this local intent.")


class FailingNotificationModel:
    async def respond(self, **kwargs):
        return CommunicationModelResult(reply_text="unused", conversational_act="model_reply")

    async def render_notification(self, **kwargs):
        raise RuntimeError("notification model unavailable")


@pytest.mark.anyio
async def test_notification_summary_fallback_emits_diagnostic_failure():
    store = InMemoryBlackboard()
    diagnostic_store = InMemoryDiagnosticStore()
    observability = CommunicationDiagnosticEmitter(DiagnosticLogger(store=diagnostic_store))
    brain = CommunicationBrain(store, FailingNotificationModel(), observability=observability)
    candidate = NotificationCandidate(
        candidate_id="candidate-1",
        task_id="task-1",
        candidate_type=NotificationCandidateType.COMPLETED,
        priority="p2",
        summary_short="Task completed.",
        created_at="2026-05-29T00:00:00+00:00",
        merge_key="task-1:completed",
    )

    result = await brain.emit_notification("conv-1", candidates=[candidate])

    assert result.reply_text == "Task completed."
    events = list(diagnostic_store.all())
    failed = next(item for item in events if item.event_name == "comm.reply.failed")
    assert failed.reason_code == "communication_model_failure"
    assert failed.details["error_type"] == "RuntimeError"
    assert failed.details["error_message"] == "notification model unavailable"


def _build_brain_with_runtime_like_control(
    store: InMemoryBlackboard,
    model=None,
) -> tuple[CommunicationBrain, InMemoryConversationHistory]:
    history = InMemoryConversationHistory()

    async def apply_command(command):
        await store.append_command(command)
        task = await store.get_task(command.task_id)
        if task is None:
            return []
        if command.command_type == TaskCommandType.CANCEL_TASK:
            task.status = TaskStatus.CANCELLED
        elif command.command_type == TaskCommandType.RESUME_TASK:
            task.status = TaskStatus.QUEUED
        await store.put_task(task)
        return [task.task_id]

    async def apply_interaction_request(
        request_id,
        *,
        action,
        answer_text=None,
        option_id=None,
        reason=None,
    ):
        request = await store.get_interaction_request(request_id)
        if request is None:
            return []
        updated = request.model_copy(
            update={
                "status": InteractionRequestStatus.APPROVED
                if action == "approve"
                else InteractionRequestStatus.DENIED
                if action == "deny"
                else InteractionRequestStatus.ANSWERED
                if action == "answer"
                else InteractionRequestStatus.RESOLVED
                if action == "confirm"
                else InteractionRequestStatus.CANCELLED,
            }
        )
        await store.put_interaction_request(updated)
        task = await store.get_task(request.task_id)
        return [task.task_id] if task is not None else []

    registry = build_default_tool_registry(
        store,
        executor_types=["codex", "mock"],
        default_executor_type="codex",
        apply_task_command=apply_command,
        apply_interaction_request=apply_interaction_request,
    )
    if model is None:
        model = ScriptedCommunicationModel(
            {
                "__default__": ScriptedPlan(
                    conversational_act="model_reply",
                    reply_override="Noted.",
                )
            }
        )
    return CommunicationBrain(store, model, history=history, tool_registry=registry), history


@pytest.mark.anyio
async def test_communication_brain_local_stop_cancels_last_focused_task():
    store = InMemoryBlackboard()
    task = Task(
        task_id="task-weather",
        root_task_id="task-weather",
        title="Check Shanghai's Weather",
        goal="Retrieve today's weather for Shanghai.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    other = Task(
        task_id="task-cpu",
        root_task_id="task-cpu",
        title="Check PC CPU Usage",
        goal="Retrieve current CPU usage.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    await store.put_task(other)
    await store.put_task(task)
    model = ScriptedCommunicationModel(
        {
            "forget it": ScriptedPlan(
                conversational_act="acknowledge_and_hold",
                tool_calls=[
                    ToolCall(
                        name="control_task",
                        args={"task_id": task.task_id, "command_type": TaskCommandType.CANCEL_TASK.value},
                    )
                ],
                reply_override="Okay, I won't continue with Check Shanghai's Weather.",
            )
        }
    )
    brain, history = _build_brain_with_runtime_like_control(store, model)
    history.append_assistant("conv-1", "I'll check the weather.", focused_task_id=task.task_id, affected_task_ids=[task.task_id])

    result = await brain.handle_user_message("conv-1", "forget it")

    saved_weather = await store.get_task(task.task_id)
    saved_cpu = await store.get_task(other.task_id)
    assert result.reply_text == "Okay, I won't continue with Check Shanghai's Weather."
    assert result.affected_task_ids == [task.task_id]
    assert saved_weather is not None and saved_weather.status == TaskStatus.CANCELLED
    assert saved_cpu is not None and saved_cpu.status == TaskStatus.CREATED


@pytest.mark.anyio
async def test_communication_brain_local_stop_asks_when_no_valid_focus_exists():
    store = InMemoryBlackboard()
    model = ScriptedCommunicationModel(
        {
            "stop it": ScriptedPlan(
                conversational_act="request_clarification",
                reply_override="Which task do you want me to stop?",
            )
        }
    )
    brain, _history = _build_brain_with_runtime_like_control(store, model)

    result = await brain.handle_user_message("conv-1", "stop it")

    assert result.conversational_act == "request_clarification"
    assert result.reply_text == "Which task do you want me to stop?"


@pytest.mark.anyio
async def test_communication_brain_continue_recreates_cancelled_task():
    store = InMemoryBlackboard()
    cancelled = Task(
        task_id="task-weather-old",
        root_task_id="task-weather-old",
        title="Check Shanghai's Weather",
        goal="Retrieve today's weather for Shanghai.",
        status=TaskStatus.CANCELLED,
        priority=7,
        preferred_executor="codex",
        latest_instruction="Use today's forecast.",
        session_affinity="workspace-1",
        metadata={
            "notes": ["Use concise wording."],
            "constraints": [{"constraint": "Do not browse unrelated cities.", "category": "scope"}],
        },
    )
    await store.put_task(cancelled)
    model = ScriptedCommunicationModel(
        {
            "i don't want to cancel it": ScriptedPlan(
                conversational_act="acknowledge_and_start",
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        args={
                            "title": "Check Shanghai's Weather Copy",
                            "goal": cancelled.goal,
                            "preferred_executor": cancelled.preferred_executor,
                            "mock_safe": False,
                        },
                    ),
                    ToolCall(
                        name="add_task_note",
                        args={"reference": "Copy", "note": "Use concise wording."},
                    ),
                    ToolCall(
                        name="add_constraint",
                        args={
                            "reference": "Copy",
                            "constraint": "Do not browse unrelated cities.",
                            "category": "scope",
                        },
                    ),
                    ToolCall(
                        name="update_task",
                        args={
                            "reference": "Copy",
                            "patch": {
                                "title": cancelled.title,
                                "priority": cancelled.priority,
                                "latest_instruction": cancelled.latest_instruction,
                                "session_affinity": cancelled.session_affinity,
                            },
                        },
                    ),
                ],
                reply_override="Okay, I'll start Check Shanghai's Weather again.",
            )
        }
    )
    brain, history = _build_brain_with_runtime_like_control(store, model)
    history.append_assistant(
        "conv-1",
        "Okay, I won't continue with Check Shanghai's Weather.",
        focused_task_id=cancelled.task_id,
        affected_task_ids=[cancelled.task_id],
    )

    result = await brain.handle_user_message("conv-1", "i don't want to cancel it")

    tasks = await store.list_tasks()
    recreated = [task for task in tasks if task.task_id != cancelled.task_id]
    assert result.conversational_act == "acknowledge_and_start"
    assert len(recreated) == 1
    assert recreated[0].goal == cancelled.goal
    assert recreated[0].priority == cancelled.priority
    assert recreated[0].latest_instruction == cancelled.latest_instruction
    assert recreated[0].session_affinity == cancelled.session_affinity
    assert recreated[0].metadata["notes"] == ["Use concise wording."]
    assert recreated[0].metadata["constraints"] == [
        {"constraint": "Do not browse unrelated cities.", "category": "scope"}
    ]
    assert result.affected_task_ids == [recreated[0].task_id]
    saved_old = await store.get_task(cancelled.task_id)
    assert saved_old is not None and saved_old.status == TaskStatus.CANCELLED


@pytest.mark.anyio
async def test_communication_brain_model_can_resolve_pending_interaction_request_via_tool():
    store = InMemoryBlackboard()
    task = Task(
        task_id="task-delete",
        root_task_id="task-delete",
        title="Delete folder",
        goal="Delete folder",
        status=TaskStatus.WAITING_USER_INPUT,
        preferred_executor="codex",
    )
    await store.put_task(task)
    await store.put_interaction_request(
        InteractionRequest(
            request_id="ireq-delete",
            task_id="task-delete",
            kind=InteractionRequestKind.PERMISSION,
            status=InteractionRequestStatus.PENDING,
            prompt="Allow deleting the folder?",
            available_actions=["approve", "deny"],
            created_at="2026-04-21T00:00:00+00:00",
        )
    )
    model = ScriptedCommunicationModel(
        {
            "确认执行": ScriptedPlan(
                conversational_act="acknowledge_and_start",
                tool_calls=[
                    ToolCall(
                        name="resolve_interaction_request",
                        args={"request_id": "ireq-delete", "action": "approve"},
                    )
                ],
                reply_override="好的，我继续执行。",
            )
        }
    )
    brain, history = _build_brain_with_runtime_like_control(store, model)
    history.append_assistant(
        "conv-1",
        "I need your confirmation before I continue.",
        focused_task_id=task.task_id,
        affected_task_ids=[task.task_id],
    )

    result = await brain.handle_user_message("conv-1", "确认执行")

    resolved = await store.get_interaction_request("ireq-delete")
    assert result.conversational_act == "acknowledge_and_start"
    assert result.reply_text == "好的，我继续执行。"
    assert result.affected_task_ids == ["task-delete"]
    assert resolved is not None and resolved.status == InteractionRequestStatus.APPROVED


@pytest.mark.anyio
async def test_communication_brain_current_work_reports_active_task_not_cancelled_one():
    store = InMemoryBlackboard()
    cancelled = Task(
        task_id="task-cpu",
        root_task_id="task-cpu",
        title="Check PC CPU Usage",
        goal="Retrieve current CPU usage.",
        status=TaskStatus.CANCELLED,
        preferred_executor="codex",
    )
    weather = Task(
        task_id="task-weather",
        root_task_id="task-weather",
        title="Check Shanghai's Weather",
        goal="Retrieve today's weather for Shanghai.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    await store.put_task(cancelled)
    await store.put_task(weather)
    model = ScriptedCommunicationModel(
        {
            "what are you working with?": lambda context: ScriptedPlan(
                conversational_act="inform_progress",
                reply_override=f"I'm working on {context.active_tasks[0].title} right now."
                if context.active_tasks
                else "I'm not actively working on anything right now.",
            )
        }
    )
    brain, _history = _build_brain_with_runtime_like_control(store, model)

    result = await brain.handle_user_message("conv-1", "what are you working with?")

    assert result.conversational_act == "inform_progress"
    assert result.reply_text == "I'm working on Check Shanghai's Weather right now."
    assert result.affected_task_ids == ["task-weather"]


@pytest.mark.anyio
async def test_communication_brain_current_work_reports_nothing_when_no_active_tasks():
    store = InMemoryBlackboard()
    model = ScriptedCommunicationModel(
        {
            "what are you working on?": ScriptedPlan(
                conversational_act="inform_progress",
                reply_override="I'm not actively working on anything right now.",
            )
        }
    )
    brain, _history = _build_brain_with_runtime_like_control(store, model)

    result = await brain.handle_user_message("conv-1", "what are you working on?")

    assert result.reply_text == "I'm not actively working on anything right now."
    assert result.affected_task_ids == []


@pytest.mark.anyio
async def test_communication_brain_model_driven_ambiguous_correction_asks_clarification_for_bundle():
    store = InMemoryBlackboard()
    flight = Task(
        task_id="task-flight",
        root_task_id="task-flight",
        title="Find flights to Beijing",
        goal="Search and list available flights from Shanghai to Beijing for tomorrow.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    hotel = Task(
        task_id="task-hotel",
        root_task_id="task-hotel",
        title="Book hotel in Beijing",
        goal="Find and book a hotel in Beijing for tomorrow.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    await store.put_task(flight)
    await store.put_task(hotel)
    model = ScriptedCommunicationModel(
        {
            "oh it should be shanghai": ScriptedPlan(
                conversational_act="request_clarification",
                reply_override="Do you mean the destination should be Shanghai instead of Beijing?",
            )
        }
    )
    brain, history = _build_brain_with_runtime_like_control(store, model)
    history.append_assistant(
        "conv-1",
        "I've started finding flights to Beijing and booking a hotel there for tomorrow.",
        focused_task_id=flight.task_id,
        focused_task_ids=[flight.task_id, hotel.task_id],
        affected_task_ids=[flight.task_id, hotel.task_id],
    )

    result = await brain.handle_user_message("conv-1", "oh it should be shanghai")

    assert result.conversational_act == "request_clarification"
    assert result.reply_text == "Do you mean the destination should be Shanghai instead of Beijing?"
    saved_flight = await store.get_task(flight.task_id)
    saved_hotel = await store.get_task(hotel.task_id)
    assert saved_flight is not None and saved_flight.status == TaskStatus.CREATED
    assert saved_hotel is not None and saved_hotel.status == TaskStatus.CREATED


@pytest.mark.anyio
async def test_communication_brain_model_driven_explicit_correction_replaces_bundle():
    store = InMemoryBlackboard()
    flight = Task(
        task_id="task-flight",
        root_task_id="task-flight",
        title="Find flights to Beijing",
        goal="Search and list available flights from Shanghai to Beijing for tomorrow.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    hotel = Task(
        task_id="task-hotel",
        root_task_id="task-hotel",
        title="Book hotel in Beijing",
        goal="Find and book a hotel in Beijing for tomorrow.",
        status=TaskStatus.CREATED,
        preferred_executor="codex",
    )
    await store.put_task(flight)
    await store.put_task(hotel)
    model = ScriptedCommunicationModel(
        {
            "travel to Shanghai instead of Beijing": ScriptedPlan(
                conversational_act="acknowledge_and_modify",
                tool_calls=[
                    ToolCall(
                        name="create_task",
                        args={
                            "title": "Find flights to Shanghai",
                            "goal": "Search and list available flights from Shanghai to Shanghai for tomorrow.",
                            "preferred_executor": "codex",
                            "mock_safe": False,
                        },
                    ),
                    ToolCall(
                        name="create_task",
                        args={
                            "title": "Book hotel in Shanghai",
                            "goal": "Find and book a hotel in Shanghai for tomorrow.",
                            "preferred_executor": "codex",
                            "mock_safe": False,
                        },
                    ),
                    ToolCall(
                        name="control_task",
                        args={"task_id": flight.task_id, "command_type": TaskCommandType.CANCEL_TASK.value},
                    ),
                    ToolCall(
                        name="control_task",
                        args={"task_id": hotel.task_id, "command_type": TaskCommandType.CANCEL_TASK.value},
                    ),
                ],
                reply_override="Okay, I replaced Beijing with Shanghai in those tasks.",
            )
        }
    )
    brain, history = _build_brain_with_runtime_like_control(store, model)
    history.append_assistant(
        "conv-1",
        "I've started finding flights to Beijing and booking a hotel there for tomorrow.",
        focused_task_id=flight.task_id,
        focused_task_ids=[flight.task_id, hotel.task_id],
        affected_task_ids=[flight.task_id, hotel.task_id],
    )

    result = await brain.handle_user_message("conv-1", "travel to Shanghai instead of Beijing")

    tasks = await store.list_tasks()
    new_tasks = [task for task in tasks if task.task_id not in {flight.task_id, hotel.task_id}]
    assert result.conversational_act == "acknowledge_and_modify"
    assert result.reply_text == "Okay, I replaced Beijing with Shanghai in those tasks."
    assert len(new_tasks) == 2
    assert set(result.affected_task_ids) == {flight.task_id, hotel.task_id, *[task.task_id for task in new_tasks]}
    assert any("Shanghai" in task.title and "Beijing" not in task.title for task in new_tasks)
    assert any("Shanghai" in task.goal and "Beijing" not in task.goal for task in new_tasks)
    saved_flight = await store.get_task(flight.task_id)
    saved_hotel = await store.get_task(hotel.task_id)
    assert saved_flight is not None and saved_flight.status == TaskStatus.CANCELLED
    assert saved_hotel is not None and saved_hotel.status == TaskStatus.CANCELLED


@pytest.mark.anyio
async def test_communication_brain_downgrades_write_reply_without_affected_task_ids():
    store = InMemoryBlackboard()
    model = ScriptedCommunicationModel(
        {
            "Make it shorter": ScriptedPlan(
                conversational_act="acknowledge_and_modify",
                reply_override="Okay, I updated that.",
            )
        }
    )
    brain, _history = _build_brain_with_runtime_like_control(store, model)

    result = await brain.handle_user_message("conv-1", "Make it shorter")

    assert result.conversational_act == "request_clarification"
    assert result.reply_text == "Can you clarify which task you mean?"
