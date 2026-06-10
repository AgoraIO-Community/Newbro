from __future__ import annotations

from pathlib import Path

from pydantic import PrivateAttr

from newbro.executors.core import ExecutorSession


class HermesExecutorSession(ExecutorSession):
    _cwd: Path | None = PrivateAttr(default=None)
    _gateway_session_id: str | None = PrivateAttr(default=None)

    def attach(self, *, cwd: Path, gateway_session_id: str) -> None:
        self._cwd = cwd
        self._gateway_session_id = gateway_session_id
        self.session_id = gateway_session_id
        self.metadata.update({"cwd": str(cwd), "gateway_session_id": gateway_session_id})

    @property
    def cwd(self) -> Path:
        if self._cwd is None:
            raise RuntimeError("Hermes cwd not attached.")
        return self._cwd

    @property
    def gateway_session_id(self) -> str:
        if self._gateway_session_id is None:
            raise RuntimeError("Hermes gateway session id not attached.")
        return self._gateway_session_id
