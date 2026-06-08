from __future__ import annotations

import asyncio
import logging

import pytest

from newbro.executors.node.registry import ExecutorNodeRegistry
from newbro.protocol import (
    CodexThreadTurnsListedMessage,
    CodexThreadsListedMessage,
    CodexThreadSubscribedMessage,
    CodexThreadUnsubscribedMessage,
    CodexTurnEventMessage,
    ExecutorNodeExecutor,
    ExecutorTextInstruction,
    RegisterNodeMessage,
)
from newbro.runtime.executor_node_manager import ExecutorNodeManager, RunDispatchState


async def _registered_manager_with_issue(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    return issue, manager


@pytest.mark.anyio
async def test_disconnect_notifies_waiting_runs_and_clears_tracking(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    first_socket = object()
    issue = await manager.create_node(
        name="Node One",
        enabled_executors=["codex"],
    )

    await manager.register_connection(
        first_socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex")],
        ),
    )
    stale_queue: asyncio.Queue = asyncio.Queue()
    manager._run_queues["run-stale"] = stale_queue
    manager._run_states["run-stale"] = RunDispatchState(
        run_id="run-stale",
        execution_session_id="exec-stale",
        executor_type="codex",
        node_id=issue.node.node_id,
    )

    await manager.disconnect(websocket=first_socket, reason="connection_closed")

    event = await stale_queue.get()
    assert event.event.event_type.value == "waiting_executor"
    assert event.event.message == f"Waiting for executor node '{issue.node.node_id}' to reconnect."
    assert event.event.metadata == {
        "executor_node_id": issue.node.node_id,
        "availability_reason": "connection_closed",
    }
    assert manager._run_queues == {}
    assert manager._run_states == {}


@pytest.mark.anyio
async def test_sends_to_one_node_do_not_block_another(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    first_issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    second_issue = await manager.create_node(name="Node Two", enabled_executors=["codex"])

    first_release = asyncio.Event()
    second_sent = asyncio.Event()

    class SlowSocket:
        def __init__(self, sent_event: asyncio.Event | None = None, release_event: asyncio.Event | None = None):
            self.sent_event = sent_event
            self.release_event = release_event

        async def send_json(self, payload: dict[str, object]) -> None:
            if self.sent_event is not None:
                self.sent_event.set()
            if self.release_event is not None:
                await self.release_event.wait()

    await manager.register_connection(
        SlowSocket(release_event=first_release),
        RegisterNodeMessage(
            node_id=first_issue.node.node_id,
            token=first_issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex")],
        ),
    )
    await manager.register_connection(
        SlowSocket(sent_event=second_sent),
        RegisterNodeMessage(
            node_id=second_issue.node.node_id,
            token=second_issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex")],
        ),
    )

    first_connection = manager._connections_by_node[first_issue.node.node_id]
    second_connection = manager._connections_by_node[second_issue.node.node_id]

    first_task = asyncio.create_task(manager._send_json(first_connection, {"type": "first"}))
    second_task = asyncio.create_task(manager._send_json(second_connection, {"type": "second"}))

    await asyncio.wait_for(second_sent.wait(), timeout=1.0)
    first_release.set()
    await asyncio.gather(first_task, second_task)


@pytest.mark.anyio
async def test_selected_codex_thread_subscription_request_round_trip(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.subscribe_codex_thread(
            node_id=issue.node.node_id,
            subscription_id="sub-1",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
            workspace_id="/tmp/workspace",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "subscribe_codex_thread"
    assert command["subscription_id"] == "sub-1"
    assert command["thread_id"] == "codex-thread-1"
    assert command["workspace_id"] == "/tmp/workspace"

    manager.publish_codex_thread_subscribed(
        CodexThreadSubscribedMessage(
            request_id=str(command["request_id"]),
            subscription_id="sub-1",
            node_id=issue.node.node_id,
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
        )
    )
    response = await task
    assert response.subscription_id == "sub-1"

    sent_event.clear()
    task = asyncio.create_task(
        manager.unsubscribe_codex_thread(
            node_id=issue.node.node_id,
            subscription_id="sub-1",
            thread_id="codex-thread-1",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "unsubscribe_codex_thread"
    assert command["subscription_id"] == "sub-1"

    manager.publish_codex_thread_unsubscribed(
        CodexThreadUnsubscribedMessage(
            request_id=str(command["request_id"]),
            subscription_id="sub-1",
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            status="unsubscribed",
        )
    )
    response = await task
    assert response.status == "unsubscribed"


@pytest.mark.anyio
async def test_subscribe_codex_thread_logs_round_trip_timing(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="newbro.runtime.executor_node_manager")
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.subscribe_codex_thread(
            node_id=issue.node.node_id,
            subscription_id="sub-1",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
            workspace_id="/tmp/workspace",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]

    manager.publish_codex_thread_subscribed(
        CodexThreadSubscribedMessage(
            request_id=str(command["request_id"]),
            subscription_id="sub-1",
            node_id=issue.node.node_id,
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
        )
    )
    response = await task
    assert response.subscription_id == "sub-1"

    assert any("codex_thread subscribe round-trip" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_selected_codex_thread_subscription_requests_cleanup_on_cancel(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    sent_event = asyncio.Event()

    class CapturingSocket:
        async def send_json(self, payload: dict[str, object]) -> None:
            sent_event.set()

    await manager.register_connection(
        CapturingSocket(),
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.subscribe_codex_thread(
            node_id=issue.node.node_id,
            subscription_id="sub-1",
            session_id="session-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            thread_id="codex-thread-1",
            workspace_id="/tmp/workspace",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    assert len(manager._codex_thread_subscribe_requests) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager._codex_thread_subscribe_requests == {}

    sent_event.clear()
    task = asyncio.create_task(
        manager.unsubscribe_codex_thread(
            node_id=issue.node.node_id,
            subscription_id="sub-1",
            thread_id="codex-thread-1",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    assert len(manager._codex_thread_unsubscribe_requests) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager._codex_thread_unsubscribe_requests == {}


@pytest.mark.anyio
async def test_request_codex_threads_sends_cursor_page_command(tmp_path):
    issue, manager = await _registered_manager_with_issue(tmp_path)
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.request_codex_threads(
            node_id=issue.node.node_id,
            workspace_id="/tmp/work",
            limit=25,
            cursor="cursor-1",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "list_codex_threads"
    assert command["workspace_id"] == "/tmp/work"
    assert command["limit"] == 25
    assert command["cursor"] == "cursor-1"
    assert command["sort_key"] == "updated_at"
    assert command["sort_direction"] == "desc"

    manager.publish_codex_threads_listed(
        CodexThreadsListedMessage(
            request_id=str(command["request_id"]),
            node_id=issue.node.node_id,
            threads=[],
            next_cursor="cursor-2",
            previous_cursor=None,
        )
    )
    page = await task
    assert page.threads == []
    assert page.next_cursor == "cursor-2"
    assert page.previous_cursor is None


@pytest.mark.anyio
async def test_request_codex_thread_turns_sends_cursor_page_command(tmp_path):
    issue, manager = await _registered_manager_with_issue(tmp_path)
    sent_event = asyncio.Event()

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)
            sent_event.set()

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    task = asyncio.create_task(
        manager.request_codex_thread_turns(
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            limit=50,
            cursor="older",
        )
    )
    await asyncio.wait_for(sent_event.wait(), timeout=1.0)
    command = socket.sent[-1]
    assert command["type"] == "list_codex_thread_turns"
    assert command["thread_id"] == "codex-thread-1"
    assert command["limit"] == 50
    assert command["cursor"] == "older"
    assert command["sort_direction"] == "desc"
    assert command["items_view"] == "full"

    manager.publish_codex_thread_turns_listed(
        CodexThreadTurnsListedMessage(
            request_id=str(command["request_id"]),
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            turns=[],
            next_cursor=None,
            previous_cursor="newer",
        )
    )
    page = await task
    assert page.turns == []
    assert page.next_cursor is None
    assert page.previous_cursor == "newer"


@pytest.mark.anyio
async def test_unsupported_codex_node_does_not_support_thread_list(tmp_path):
    issue, manager = await _registered_manager_with_issue(tmp_path)
    await manager.register_connection(
        object(),
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[
                ExecutorNodeExecutor(
                    executor_type="codex",
                    supports_thread_list=True,
                    availability_reason="unsupported_codex_version",
                )
            ],
        ),
    )

    assert manager.executor_supports_thread_list("codex", node_id=issue.node.node_id) is False


@pytest.mark.anyio
async def test_start_codex_turn_serializes_without_task_run_or_execution_session_ids(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])

    class CapturingSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)

    socket = CapturingSocket()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex")],
        ),
    )

    sent = await manager.start_codex_turn(
        request_id="out-turn-1",
        node_id=issue.node.node_id,
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="codex-thread-1",
        instruction=ExecutorTextInstruction(
            instruction_id="txt-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Continue.",
        ),
        metadata={"client_request_id": "client-1"},
    )

    assert sent is True
    command = socket.sent[-1]
    assert command["type"] == "start_codex_turn"
    assert command["request_id"] == "out-turn-1"
    assert command["thread_id"] == "codex-thread-1"
    assert "task_id" not in command
    assert "run_id" not in command
    assert "execution_session_id" not in command


@pytest.mark.anyio
async def test_codex_turn_event_requires_matching_node(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    socket = object()
    await manager.register_connection(
        socket,
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex")],
        ),
    )

    ack = await manager.publish_codex_turn_event(
        socket,
        CodexTurnEventMessage(
            request_id="out-turn-1",
            node_id="other-node",
            target_persona_id="forge",
            target_thread_id="thread-1",
            event_type="progress",
        ),
    )

    assert ack.ok is False
    assert ack.detail == "unauthorized_node"


@pytest.mark.anyio
async def test_codex_thread_read_timeout_has_user_visible_message(tmp_path):
    manager = ExecutorNodeManager(
        detached_executor_types=("codex",),
        registry=ExecutorNodeRegistry(path=tmp_path / "executor_nodes.yaml"),
    )
    issue = await manager.create_node(name="Node One", enabled_executors=["codex"])
    sent_event = asyncio.Event()

    class CapturingSocket:
        async def send_json(self, payload: dict[str, object]) -> None:
            sent_event.set()

    await manager.register_connection(
        CapturingSocket(),
        RegisterNodeMessage(
            node_id=issue.node.node_id,
            token=issue.token,
            executors=[ExecutorNodeExecutor(executor_type="codex", supports_thread_list=True)],
        ),
    )

    with pytest.raises(TimeoutError, match="Timed out reading Codex thread history."):
        await manager.request_codex_thread(
            node_id=issue.node.node_id,
            thread_id="codex-thread-1",
            timeout_seconds=0.01,
        )
    assert sent_event.is_set()
