import pytest

from newbro.observability.latency import LatencyTracker


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _tracker():
    clock = _Clock()
    emitted = []
    tracker = LatencyTracker(emit=lambda **kw: emitted.append(kw), now=clock, ttl_seconds=120.0)
    return tracker, clock, emitted


def test_assembles_named_spans_and_total():
    tracker, clock, emitted = _tracker()
    clock.t = 1.000; tracker.mark("k", "runtime.received")
    clock.t = 1.020; tracker.mark("k", "runtime.executor_ready")
    clock.t = 1.030; tracker.mark("k", "runtime.thread_resolved")
    clock.t = 1.040; tracker.mark("k", "runtime.active_execution_checked")
    clock.t = 1.050; tracker.mark("k", "runtime.outbound_turn_started")
    clock.t = 1.060; tracker.mark("k", "runtime.dispatch_completed")
    clock.t = 1.065; tracker.mark("k", "runtime.snapshot_published")
    clock.t = 4.000; tracker.mark("k", "executor.first_token", model_name="gpt-x")
    clock.t = 5.000; tracker.mark("k", "executor.completed")
    tracker.finish("k", outcome="completed")

    assert len(emitted) == 1
    rec = emitted[0]
    assert rec["request_id"] == "k"
    assert rec["outcome"] == "completed"
    assert rec["model_name"] == "gpt-x"
    assert rec["total_ms"] == 4000  # received -> completed
    steps = rec["steps"]
    assert steps["executor_ready"] == 20   # 1.020 - 1.000
    assert steps["dispatch"] == 10         # dispatch_completed - outbound_turn_started (1.060 - 1.050)
    assert steps["publish"] == 5           # snapshot_published - dispatch_completed (1.065 - 1.060)
    assert steps["ttft"] == 2940           # first_token - dispatch_completed (4.000 - 1.060)
    assert steps["stream"] == 1000         # completed - first_token


def test_finish_evicts_and_is_idempotent():
    tracker, clock, emitted = _tracker()
    tracker.mark("k", "runtime.received")
    tracker.finish("k")
    tracker.finish("k")  # no record left -> no second emit
    assert len(emitted) == 1


def test_missing_marks_omit_spans_no_crash():
    tracker, clock, emitted = _tracker()
    clock.t = 0.0; tracker.mark("k", "runtime.received")
    clock.t = 0.5; tracker.mark("k", "runtime.dispatch_completed")
    tracker.finish("k", outcome="completed")
    steps = emitted[0]["steps"]
    assert "ttft" not in steps and "stream" not in steps
    assert emitted[0]["total_ms"] == 500  # received -> last mark fallback


def test_sweep_emits_incomplete_for_stale_turn():
    tracker, clock, emitted = _tracker()
    clock.t = 0.0; tracker.mark("k", "runtime.received")
    clock.t = 200.0; tracker.mark("other", "runtime.received")  # triggers sweep
    assert any(e["outcome"] == "incomplete" and e["request_id"] == "k" for e in emitted)


def test_emit_failure_is_swallowed():
    clock = _Clock()
    def boom(**kw):
        raise RuntimeError("sink down")
    tracker = LatencyTracker(emit=boom, now=clock)
    tracker.mark("k", "runtime.received")
    tracker.finish("k")  # must not raise


def test_none_key_is_ignored():
    tracker, clock, emitted = _tracker()
    tracker.mark(None, "runtime.received")  # no client_request_id -> ignored
    tracker.finish(None)
    assert emitted == []
