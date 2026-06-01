from __future__ import annotations

from pathlib import Path

from newbro.executors.ui.profiles import Profile
from newbro.executors.ui.status import NodeStatus, StatusModel
from newbro.executors.ui.supervisor import ProfileSupervisor


class FakeController:
    instances: list["FakeController"] = []

    def __init__(self, *, argv, cwd, on_line, on_exit):
        self.argv = argv
        self.cwd = cwd
        self.on_line = on_line
        self.on_exit = on_exit
        self.started = False
        self.stopped = False
        FakeController.instances.append(self)

    def start(self):
        self.started = True

    def is_running(self):
        return self.started and not self.stopped

    def stop(self, *, timeout: float = 5.0):
        self.stopped = True


def make_supervisor():
    FakeController.instances = []
    return ProfileSupervisor(
        controller_factory=lambda **kw: FakeController(**kw),
        status_factory=StatusModel,
        build_argv=lambda profile: ["run", profile.node_id],
        cwd=Path.cwd(),
    )


def profile(pid="p1", node="node-1"):
    return Profile(id=pid, label=pid, base_url="https://x", node_id=node, token="t", enabled_executors=["codex"])


def test_start_spawns_controller_and_reports_starting():
    sup = make_supervisor()
    sup.start(profile())
    assert sup.active_ids() == {"p1"}
    assert sup.status_of("p1") is NodeStatus.STARTING
    assert FakeController.instances[0].argv == ["run", "node-1"]


def test_lines_drive_status_and_ready_aggregates():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    controller.on_line("[ready] executor node node_id=node-1 executors=codex newbro=https://x")
    assert sup.status_of("p1") is NodeStatus.READY
    assert sup.aggregate_status() is NodeStatus.READY


def test_user_stop_marks_stopped_and_drops_profile():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    sup.stop("p1")
    controller.on_exit(0)  # exit callback fires after terminate
    assert controller.stopped is True
    assert sup.active_ids() == set()


def test_unexpected_exit_marks_error_and_keeps_record():
    sup = make_supervisor()
    sup.start(profile())
    controller = FakeController.instances[0]
    controller.on_exit(1)
    assert sup.status_of("p1") is NodeStatus.ERROR
    assert sup.active_ids() == {"p1"}


def test_stop_all_stops_every_controller():
    sup = make_supervisor()
    sup.start(profile("p1", "node-1"))
    sup.start(profile("p2", "node-2"))
    sup.stop_all()
    assert all(c.stopped for c in FakeController.instances)


def test_log_factory_receives_node_lines():
    FakeController.instances = []

    class FakeLog:
        def __init__(self):
            self.lines: list[str] = []

        def append(self, line: str) -> None:
            self.lines.append(line)

    created: list[FakeLog] = []

    def log_factory(_profile):
        log = FakeLog()
        created.append(log)
        return log

    sup = ProfileSupervisor(
        controller_factory=lambda **kw: FakeController(**kw),
        status_factory=StatusModel,
        build_argv=lambda profile: ["run", profile.node_id],
        cwd=Path.cwd(),
        log_factory=log_factory,
    )
    sup.start(profile())
    FakeController.instances[0].on_line("[ready] executor node node_id=node-1 executors=codex newbro=https://x")
    assert created[0].lines == ["[ready] executor node node_id=node-1 executors=codex newbro=https://x"]
