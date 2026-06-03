import pytest
from newbro.observability.bootstrap import build_session_observability
from newbro.runtime.config import Settings

pytestmark = pytest.mark.anyio


def test_send_side_then_executor_marks_make_one_turn_latency():
    obs = build_session_observability(Settings())
    t = obs.latency
    for step in ["runtime.received", "runtime.executor_ready", "runtime.thread_resolved",
                 "runtime.active_execution_checked", "runtime.outbound_turn_started",
                 "runtime.dispatch_completed", "runtime.snapshot_published"]:
        t.mark("crid-1", step)
    t.mark("crid-1", "executor.first_token")
    t.mark("crid-1", "executor.completed")
    t.finish("crid-1", outcome="completed")
    evs = [e for e in obs.store.query(limit=50) if e.event_name == "turn.latency"]
    assert len(evs) == 1
    steps = evs[0].details["steps"]
    assert "ttft" in steps and "stream" in steps
