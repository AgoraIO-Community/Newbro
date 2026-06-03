import pytest

from newbro.api.ws.executors import _handle_control_message
from newbro.protocol import AckMessage, WorkspaceFileChunk

pytestmark = pytest.mark.anyio


class _Manager:
    def __init__(self):
        self.calls = []

    def publish_workspace_file_chunk(self, message):
        self.calls.append(message)
        return AckMessage(message_type=message.type, detail="ok")


class _Container:
    def __init__(self):
        self.executor_node_manager = _Manager()


async def test_chunk_routed_to_manager():
    container = _Container()
    payload = WorkspaceFileChunk(request_id="r1", seq=0, data="QQ==").model_dump(mode="json")
    ack = await _handle_control_message(container, websocket=None, payload=payload)
    assert ack.ok
    assert container.executor_node_manager.calls[0].request_id == "r1"
