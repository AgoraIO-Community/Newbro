import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import newbro.api.routes.workspace_files as wf
from newbro.api.paths import API_PREFIX

pytestmark = pytest.mark.anyio


class _Session:
    async def snapshot(self):
        turn = SimpleNamespace(
            turn_id="turn-1",
            thread_id="t1",
            executor_thread_id="codex-tid",
            assistant=SimpleNamespace(text="saved to /work/report.pdf"),
        )
        thread = SimpleNamespace(thread_id="t1", executor_node_id="node-1")
        return SimpleNamespace(bro_timeline_turns=[turn], bro_threads=[thread])


class _Manager:
    def __init__(self):
        self.last_call = None

    async def read_workspace_file(self, *, node_id, thread_id, path, executor_thread_id=None):
        self.last_call = {
            "node_id": node_id,
            "thread_id": thread_id,
            "path": path,
            "executor_thread_id": executor_thread_id,
        }
        for block in (b"hel", b"lo"):
            yield block
    node_id = "node-1"


class _Container:
    def get_session(self, session_id):
        if session_id != "s1":
            raise KeyError(session_id)
        return _Session()
    executor_node_manager = _Manager()


@pytest.fixture
def app(monkeypatch):
    application = FastAPI()
    application.state.runtime_container = _Container()
    async def _ok(request, session_id):
        return SimpleNamespace(user_id="u1")
    monkeypatch.setattr(wf, "require_session_owner", _ok)
    application.include_router(wf.router, prefix=API_PREFIX)
    return application


async def test_downloads_in_message_in_workspace_file(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/turn-1/file", params={"path": "/work/report.pdf"})
    assert resp.status_code == 200
    assert resp.content == b"hello"
    assert "attachment" in resp.headers["content-disposition"]
    # the turn's codex thread id is forwarded so the node can resolve the workspace
    assert app.state.runtime_container.executor_node_manager.last_call["executor_thread_id"] == "codex-tid"


async def test_path_not_in_turn_is_forbidden(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/turn-1/file", params={"path": "/etc/passwd"})
    assert resp.status_code == 403


async def test_unknown_turn_is_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"{API_PREFIX}/sessions/s1/bro-threads/t1/turns/nope/file", params={"path": "/work/report.pdf"})
    assert resp.status_code == 404
