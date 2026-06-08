import pytest

from newbro.executors.adapters.codex.client import CodexAppServerClient


class FakePeer:
    def __init__(self):
        self.last = None

    async def request(self, method, params=None):
        self.last = (method, params)
        return {"turn": {"id": "t1"}}


@pytest.mark.anyio
async def test_turn_start_with_skill_adds_item_and_marker():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(
        thread_id="th",
        prompt="find me flights",
        skill={"name": "flight-search", "path": "/s/flight/SKILL.md"},
    )
    _, params = peer.last
    items = params["input"]
    assert items[0]["type"] == "text"
    assert items[0]["text"].startswith("$flight-search ")
    assert {"type": "skill", "name": "flight-search", "path": "/s/flight/SKILL.md"} in items


@pytest.mark.anyio
async def test_turn_start_without_skill_unchanged():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(thread_id="th", prompt="hello")
    _, params = peer.last
    assert len(params["input"]) == 1
    assert params["input"][0]["text"] == "hello"


@pytest.mark.anyio
async def test_turn_start_marker_only_when_path_missing():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    await client.turn_start(thread_id="th", prompt="go", skill={"name": "deep-research", "path": None})
    _, params = peer.last
    assert params["input"][0]["text"].startswith("$deep-research ")
    assert all(i["type"] != "skill" for i in params["input"])
