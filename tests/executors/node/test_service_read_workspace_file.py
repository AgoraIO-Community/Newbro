import asyncio
import base64
import json
import pytest

from newbro.executors.node.service import ExecutorNodeService
from newbro.protocol import ReadWorkspaceFileCommand

pytestmark = pytest.mark.anyio


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, data):
        self.sent.append(json.loads(data))


def _make_service() -> ExecutorNodeService:
    service = ExecutorNodeService.__new__(ExecutorNodeService)
    service._thread_workspaces = {}
    service._codex_thread_workspaces = {}
    service._send_lock = asyncio.Lock()
    return service


async def test_read_resolves_imported_thread_via_codex_cwd(tmp_path):
    # Imported/history thread: no subscribe binding, but the node learned the
    # codex thread's cwd from list_threads. Gate 2 resolves the root from it.
    root = tmp_path / "obsidian"
    (root / "DevX").mkdir(parents=True)
    (root / "DevX" / "report.md").write_bytes(b"hi")
    service = _make_service()
    service._codex_thread_workspaces["codex-tid"] = str(root)
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(
        request_id="r1",
        thread_id="codex-import-abc123",  # public hash id, not in _thread_workspaces
        executor_thread_id="codex-tid",
        path=str(root / "DevX" / "report.md"),
    )
    await service._read_workspace_file(ws, cmd)
    chunks = [m for m in ws.sent if m["type"] == "workspace_file_chunk"]
    assert b"".join(base64.b64decode(c["data"]) for c in chunks) == b"hi"
    assert ws.sent[-1]["type"] == "workspace_file_eof"


async def test_read_denies_imported_thread_without_codex_binding():
    service = _make_service()
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(
        request_id="r1",
        thread_id="codex-import-abc123",
        executor_thread_id="codex-unknown",
        path="/x",
    )
    await service._read_workspace_file(ws, cmd)
    assert ws.sent[-1]["type"] == "workspace_file_error"
    assert ws.sent[-1]["code"] == "denied"


async def test_read_denies_when_no_workspace_binding():
    service = _make_service()
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="unknown", path="/x")
    await service._read_workspace_file(ws, cmd)
    assert ws.sent[-1]["type"] == "workspace_file_error"
    assert ws.sent[-1]["code"] == "denied"


async def test_read_streams_chunks_then_eof(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")
    service = _make_service()
    service._thread_workspaces["t1"] = str(root)
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path=str(root / "a.txt"))
    await service._read_workspace_file(ws, cmd)
    chunks = [m for m in ws.sent if m["type"] == "workspace_file_chunk"]
    eofs = [m for m in ws.sent if m["type"] == "workspace_file_eof"]
    assert b"".join(base64.b64decode(c["data"]) for c in chunks) == b"hello"
    assert eofs and eofs[-1]["total_bytes"] == 5


async def test_read_denies_outside_workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    service = _make_service()
    service._thread_workspaces["t1"] = str(root)
    ws = _FakeWS()
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path="/etc/hosts")
    await service._read_workspace_file(ws, cmd)
    assert ws.sent[-1]["type"] == "workspace_file_error"
    assert ws.sent[-1]["code"] == "denied"
