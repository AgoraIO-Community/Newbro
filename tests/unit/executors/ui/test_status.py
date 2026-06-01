from __future__ import annotations

from newbro.executors.ui.status import NodeStatus, StatusModel, aggregate_status


def feed(model: StatusModel, lines: list[str]) -> NodeStatus:
    model.on_start()
    for line in lines:
        model.on_line(line)
    return model.status


def test_status_transitions_through_connect_to_ready():
    model = StatusModel()
    status = feed(
        model,
        [
            "[start] executor node node_id=node-1 executors=codex newbro=https://x",
            "[connect] executor node attempt=1 url=wss://x/api/executors/control",
            "[ready] executor node node_id=node-1 executors=codex newbro=https://x",
        ],
    )
    assert status is NodeStatus.READY


def test_status_reflects_disconnect_and_retry():
    model = StatusModel()
    feed(model, ["[ready] executor node node_id=node-1 executors=codex newbro=https://x"])
    model.on_line("[warn] executor node disconnected=ConnectionClosed url=wss://x")
    assert model.status is NodeStatus.DISCONNECTED
    model.on_line("[retry] executor node retrying in 2.0s")
    assert model.status is NodeStatus.RETRYING


def test_connect_failed_warn_stays_connecting():
    model = StatusModel()
    model.on_start()
    model.on_line("[connect] executor node attempt=1 url=wss://x")
    model.on_line("[warn] executor node attempt=1 connect_failed=Timeout url=wss://x")
    assert model.status is NodeStatus.CONNECTING


def test_exit_expected_is_stopped_unexpected_is_error():
    model = StatusModel()
    model.on_start()
    assert model.on_exit(0, expected=True) is NodeStatus.STOPPED
    other = StatusModel()
    other.on_start()
    assert other.on_exit(1, expected=False) is NodeStatus.ERROR


def test_aggregate_prioritizes_error_then_connecting_then_ready():
    assert aggregate_status([NodeStatus.READY, NodeStatus.ERROR]) is NodeStatus.ERROR
    assert aggregate_status([NodeStatus.READY, NodeStatus.CONNECTING]) is NodeStatus.CONNECTING
    assert aggregate_status([NodeStatus.READY, NodeStatus.STOPPED]) is NodeStatus.READY
    assert aggregate_status([NodeStatus.STOPPED, NodeStatus.IDLE]) is NodeStatus.IDLE
    assert aggregate_status([]) is NodeStatus.IDLE
