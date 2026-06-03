from newbro.observability.bootstrap import build_session_observability
from newbro.runtime.config import Settings


def test_session_observability_has_latency_tracker_and_emits_turn_latency():
    obs = build_session_observability(Settings())
    assert hasattr(obs, "latency")
    obs.latency.mark("k", "runtime.received")
    obs.latency.mark("k", "executor.completed")
    obs.latency.finish("k", outcome="completed")
    events = [e for e in obs.store.query(limit=50) if e.event_name == "turn.latency"]
    assert len(events) == 1
    assert events[0].request_id == "k"
    assert "total_ms" in events[0].details and "steps" in events[0].details
