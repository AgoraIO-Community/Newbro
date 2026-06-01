from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from newbro.executors.ui.profiles import Profile
from newbro.executors.ui.status import NodeStatus, StatusModel, aggregate_status


@dataclass(slots=True)
class _Record:
    profile: Profile
    controller: Any
    status_model: StatusModel
    log: Any = None
    expected_stop: bool = False


class ProfileSupervisor:
    """Owns one controller + status model per active profile.

    The node subprocess owns its own reconnection, so the supervisor does not
    add a process-restart loop: an unexpected exit becomes ERROR and is left for
    the user to act on; a user-requested stop becomes STOPPED.
    """

    def __init__(
        self,
        *,
        controller_factory: Callable[..., Any],
        status_factory: Callable[[], StatusModel],
        build_argv: Callable[[Profile], list[str]],
        log_factory: Callable[[Profile], Any] | None = None,
        cwd: Path,
    ) -> None:
        self._controller_factory = controller_factory
        self._status_factory = status_factory
        self._build_argv = build_argv
        self._log_factory = log_factory
        self._cwd = cwd
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()

    def start(self, profile: Profile) -> None:
        with self._lock:
            if profile.id in self._records and self._records[profile.id].controller.is_running():
                return
            status_model = self._status_factory()
            status_model.on_start()
            log = self._log_factory(profile) if self._log_factory is not None else None
            record = _Record(profile=profile, controller=None, status_model=status_model, log=log)
            controller = self._controller_factory(
                argv=self._build_argv(profile),
                cwd=self._cwd,
                on_line=lambda line, pid=profile.id: self._on_line(pid, line),
                on_exit=lambda code, pid=profile.id: self._on_exit(pid, code),
            )
            record.controller = controller
            self._records[profile.id] = record
            controller.start()

    def stop(self, profile_id: str) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is None:
                return
            record.expected_stop = True
            controller = record.controller
        controller.stop()

    def restart(self, profile: Profile) -> None:
        self.stop(profile.id)
        self.start(profile)

    def _on_line(self, profile_id: str, line: str) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is None:
                return
            record.status_model.on_line(line)
            log = record.log
        if log is not None:
            log.append(line)

    def _on_exit(self, profile_id: str, code: int) -> None:
        with self._lock:
            record = self._records.get(profile_id)
            if record is None:
                return
            if record.expected_stop:
                record.status_model.on_exit(code, expected=True)
                del self._records[profile_id]
            else:
                record.status_model.on_exit(code, expected=False)

    def status_of(self, profile_id: str) -> NodeStatus:
        with self._lock:
            record = self._records.get(profile_id)
            return record.status_model.status if record else NodeStatus.IDLE

    def aggregate_status(self) -> NodeStatus:
        with self._lock:
            return aggregate_status([record.status_model.status for record in self._records.values()])

    def active_ids(self) -> set[str]:
        with self._lock:
            return set(self._records)

    def stop_all(self) -> None:
        with self._lock:
            controllers = [(record_id, record.controller) for record_id, record in self._records.items()]
            for _, record in self._records.items():
                record.expected_stop = True
        for _, controller in controllers:
            controller.stop()
