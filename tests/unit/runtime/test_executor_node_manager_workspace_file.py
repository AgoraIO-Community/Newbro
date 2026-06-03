from __future__ import annotations

import asyncio
import base64
import datetime

import pytest

from newbro.protocol import WorkspaceFileChunk, WorkspaceFileEof, WorkspaceFileError
from newbro.runtime.executor_node_manager import (
    ExecutorNodeManager,
    NodeConnectionState,
    WorkspaceFileDenied,
    WorkspaceFileUnavailable,
)

pytestmark = pytest.mark.anyio


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _manager_with_node(node_id: str = "node-1") -> tuple[ExecutorNodeManager, str]:
    manager = ExecutorNodeManager(detached_executor_types=("codex",))
    ws = _FakeWS()
    state = NodeConnectionState(
        websocket=ws,
        node_id=node_id,
        connected_at=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    )
    manager._connections_by_node[node_id] = state
    return manager, node_id


async def test_streams_chunks_until_eof():
    manager, node_id = _manager_with_node()

    async def feed():
        await asyncio.sleep(0.01)
        request_id = next(iter(manager._workspace_file_streams))
        manager.publish_workspace_file_chunk(
            WorkspaceFileChunk(request_id=request_id, seq=0, data=base64.b64encode(b"he").decode())
        )
        manager.publish_workspace_file_chunk(
            WorkspaceFileChunk(request_id=request_id, seq=1, data=base64.b64encode(b"llo").decode())
        )
        manager.publish_workspace_file_eof(WorkspaceFileEof(request_id=request_id, total_bytes=5))

    task = asyncio.create_task(feed())
    out = b""
    async for chunk in manager.read_workspace_file(node_id=node_id, thread_id="t1", path="/x"):
        out += chunk
    await task
    assert out == b"hello"


async def test_error_raises_denied():
    manager, node_id = _manager_with_node()

    async def feed():
        await asyncio.sleep(0.01)
        request_id = next(iter(manager._workspace_file_streams))
        manager.publish_workspace_file_error(
            WorkspaceFileError(request_id=request_id, code="denied", message="nope")
        )

    task = asyncio.create_task(feed())
    with pytest.raises(WorkspaceFileDenied) as exc:
        async for _ in manager.read_workspace_file(node_id=node_id, thread_id="t1", path="/x"):
            pass
    await task
    assert exc.value.code == "denied"


async def test_offline_node_raises_unavailable():
    manager = ExecutorNodeManager(detached_executor_types=("codex",))
    with pytest.raises(WorkspaceFileUnavailable):
        async for _ in manager.read_workspace_file(node_id="ghost", thread_id="t1", path="/x"):
            pass
