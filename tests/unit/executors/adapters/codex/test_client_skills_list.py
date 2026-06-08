import pytest

from newbro.executors.adapters.codex.client import CodexAppServerClient


class FakePeer:
    def __init__(self):
        self.calls = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        return {"data": []}


@pytest.mark.anyio
async def test_skills_list_sends_cwds_and_force_reload():
    peer = FakePeer()
    client = CodexAppServerClient(peer)
    result = await client.skills_list(cwds=["/repo"], force_reload=True)
    assert peer.calls == [("skills/list", {"cwds": ["/repo"], "forceReload": True})]
    assert result == {"data": []}
