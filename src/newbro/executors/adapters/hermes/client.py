from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .jsonrpc import HermesJsonRpcPeer

GATEWAY_MODULE_ARGS: list[str] = ["-m", "tui_gateway.entry"]
DEFAULT_PROJECT_ROOT = Path.home() / ".hermes" / "hermes-agent"


def resolve_gateway_launch(command: str, project_root: str | None) -> tuple[str, Path]:
    """Return (python_executable, project_root) for launching the gateway.

    project_root defaults to parsing the `Project:` line of `<command> --version`,
    falling back to ~/.hermes/hermes-agent. The gateway python is
    <project_root>/venv/bin/python3.
    """
    root: Path | None = Path(project_root) if project_root else None
    if root is None:
        try:
            completed = subprocess.run(
                [command, "--version"], check=False, capture_output=True, text=True, timeout=8
            )
            match = re.search(r"^Project:\s*(.+)$", completed.stdout or "", re.MULTILINE)
            if match:
                root = Path(match.group(1).strip())
        except Exception:  # noqa: BLE001 - fall back to the default root on any probe failure
            root = None
    if root is None:
        root = DEFAULT_PROJECT_ROOT
    return str(root / "venv" / "bin" / "python3"), root


@dataclass(slots=True)
class _GatewayProcess:
    process: asyncio.subprocess.Process
    peer: HermesJsonRpcPeer
    router_task: asyncio.Task[None] | None = None
    session_queues: dict[str, asyncio.Queue[dict[str, object]]] = field(default_factory=dict)


class HermesGatewayClient:
    """Gateway processes keyed by working directory (TERMINAL_CWD is per-process).

    Public API is session-id-keyed; a session id is internally mapped to the
    gateway process that owns it.
    """

    def __init__(self, *, command: str = "hermes", project_root: str | None = None) -> None:
        self._command = command
        self._project_root = project_root
        self._lock = asyncio.Lock()
        self._by_cwd: dict[str, _GatewayProcess] = {}
        self._gateway_by_session: dict[str, _GatewayProcess] = {}

    async def _ensure_process(self, cwd: Path) -> _GatewayProcess:
        key = str(cwd)
        async with self._lock:
            existing = self._by_cwd.get(key)
            if existing is not None and existing.process.returncode is None:
                return existing
            python_executable, root = resolve_gateway_launch(self._command, self._project_root)
            env = dict(os.environ)
            env["HERMES_PYTHON_SRC_ROOT"] = str(root)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(root), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            env["TERMINAL_CWD"] = key
            env["HERMES_CWD"] = key
            process = await asyncio.create_subprocess_exec(
                python_executable,
                *GATEWAY_MODULE_ARGS,
                cwd=key,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdout is not None and process.stdin is not None
            gateway = _GatewayProcess(process=process, peer=HermesJsonRpcPeer(process.stdout, process.stdin))
            gateway.router_task = asyncio.create_task(self._route_events(gateway))
            self._by_cwd[key] = gateway
            return gateway

    def _gateway(self, session_id: str) -> _GatewayProcess:
        gateway = self._gateway_by_session.get(session_id)
        if gateway is None:
            raise RuntimeError(f"Unknown hermes session: {session_id}")
        return gateway

    async def create_session(self, cwd: Path) -> str:
        gateway = await self._ensure_process(cwd)
        result = await gateway.peer.request("session.create", {"cols": 80})
        if not isinstance(result, dict) or "session_id" not in result:
            raise RuntimeError(f"Hermes session.create returned unexpected result: {result!r}")
        session_id = str(result["session_id"])
        gateway.session_queues.setdefault(session_id, asyncio.Queue())
        self._gateway_by_session[session_id] = gateway
        return session_id

    async def submit_prompt(self, session_id: str, text: str) -> None:
        await self._gateway(session_id).peer.request(
            "prompt.submit", {"session_id": session_id, "text": text}
        )

    async def steer(self, session_id: str, text: str) -> None:
        result = await self._gateway(session_id).peer.request(
            "session.steer", {"session_id": session_id, "text": text}
        )
        if isinstance(result, dict) and result.get("status") == "rejected":
            raise RuntimeError("hermes session.steer rejected")

    async def interrupt(self, session_id: str) -> None:
        await self._gateway(session_id).peer.request("session.interrupt", {"session_id": session_id})

    async def events_for(self, session_id: str) -> asyncio.Queue[dict[str, object]]:
        return self._gateway(session_id).session_queues.setdefault(session_id, asyncio.Queue())

    async def _route_events(self, gateway: _GatewayProcess) -> None:
        async for event in gateway.peer.iter_events():
            params = event.get("params") if isinstance(event, dict) else None
            if not isinstance(params, dict):
                continue
            session_id = params.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue  # global event (gateway.ready, skin.changed) — not session-scoped
            queue = gateway.session_queues.setdefault(session_id, asyncio.Queue())
            await queue.put(params)

    async def aclose(self) -> None:
        for gateway in list(self._by_cwd.values()):
            if gateway.router_task is not None:
                gateway.router_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await gateway.router_task
            await gateway.peer.close()
            if gateway.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    gateway.process.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(gateway.process.wait(), timeout=5.0)
        self._by_cwd.clear()
        self._gateway_by_session.clear()
