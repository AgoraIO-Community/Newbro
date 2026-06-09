# tests/unit/executors/test_hermes_jsonrpc.py
import asyncio
import json

import pytest

from newbro.executors.adapters.hermes.jsonrpc import HermesJsonRpcPeer, PEER_CLOSED


async def _make_peer_over_pipe():
    # Loopback: peer writes to `to_peer`, reads responses we inject via `from_peer`.
    reader = asyncio.StreamReader()
    transport_writes: list[bytes] = []

    class _FakeWriter:
        def write(self, data: bytes) -> None:
            transport_writes.append(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    peer = HermesJsonRpcPeer(reader, _FakeWriter())
    return peer, reader, transport_writes


@pytest.mark.anyio
async def test_request_resolves_on_matching_response():
    peer, reader, writes = await _make_peer_over_pipe()
    request = asyncio.ensure_future(peer.request("session.create", {"cwd": "/tmp"}))
    await asyncio.sleep(0)  # let the request serialize
    sent = json.loads(writes[0].decode())
    assert sent["method"] == "session.create"
    reader.feed_data(
        (json.dumps({"jsonrpc": "2.0", "id": sent["id"], "result": {"session_id": "s1"}}) + "\n").encode()
    )
    assert await request == {"session_id": "s1"}
    await peer.close()


@pytest.mark.anyio
async def test_notifications_surface_as_events():
    peer, reader, _ = await _make_peer_over_pipe()
    reader.feed_data(
        (json.dumps({"jsonrpc": "2.0", "method": "message.delta", "params": {"text": "hi"}}) + "\n").encode()
    )
    event = await peer.next_event()
    assert event["method"] == "message.delta"
    await peer.close()


@pytest.mark.anyio
async def test_eof_pushes_peer_closed_sentinel():
    """After reader EOF, next_event() must return PEER_CLOSED (not hang)."""
    peer, reader, _ = await _make_peer_over_pipe()
    reader.feed_eof()
    event = await peer.next_event()
    assert event == {"__peer_closed__": True}
    assert event == PEER_CLOSED
