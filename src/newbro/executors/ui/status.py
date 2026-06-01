from __future__ import annotations

from enum import Enum


class NodeStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    CONNECTING = "connecting"
    READY = "ready"
    DISCONNECTED = "disconnected"
    RETRYING = "retrying"
    ERROR = "error"
    STOPPED = "stopped"


class StatusModel:
    def __init__(self) -> None:
        self.status = NodeStatus.IDLE

    def on_start(self) -> NodeStatus:
        self.status = NodeStatus.STARTING
        return self.status

    def on_line(self, line: str) -> NodeStatus:
        if line.startswith("[start]"):
            self.status = NodeStatus.STARTING
        elif line.startswith("[connect]"):
            self.status = NodeStatus.CONNECTING
        elif line.startswith("[ready]"):
            self.status = NodeStatus.READY
        elif line.startswith("[retry]"):
            self.status = NodeStatus.RETRYING
        elif line.startswith("[warn]") and "disconnected=" in line:
            self.status = NodeStatus.DISCONNECTED
        elif line.startswith("[warn]") and "connect_failed=" in line:
            self.status = NodeStatus.CONNECTING
        return self.status

    def on_exit(self, code: int, *, expected: bool) -> NodeStatus:
        self.status = NodeStatus.STOPPED if expected else NodeStatus.ERROR
        return self.status


_AGGREGATE_PRIORITY = (
    NodeStatus.ERROR,
    NodeStatus.DISCONNECTED,
    NodeStatus.RETRYING,
    NodeStatus.CONNECTING,
    NodeStatus.STARTING,
    NodeStatus.READY,
)


def aggregate_status(statuses: list[NodeStatus]) -> NodeStatus:
    present = set(statuses)
    for candidate in _AGGREGATE_PRIORITY:
        if candidate in present:
            return candidate
    return NodeStatus.IDLE
