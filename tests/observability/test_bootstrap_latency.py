import pytest

from newbro.observability.bootstrap import build_latency_exporter, build_session_observability
from newbro.observability.sinks.http_exporter import HttpExporterSink
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


def test_build_latency_exporter_disabled_by_default():
    result = build_latency_exporter(Settings())
    assert result is None


def test_build_latency_exporter_enabled_returns_sink():
    result = build_latency_exporter(
        Settings(latency_export_enabled=True, latency_export_url="http://example.com/events")
    )
    assert isinstance(result, HttpExporterSink)


def test_build_latency_exporter_enabled_but_no_url_returns_none():
    result = build_latency_exporter(Settings(latency_export_enabled=True))
    assert result is None


def test_extra_sinks_injected_into_session_observability():
    """Exporter passed as extra_sink receives events emitted by the session logger."""
    from newbro.observability.schema import DiagnosticEvent
    from newbro.observability.sinks.types import DiagnosticSink

    received: list[DiagnosticEvent] = []

    class CaptureSink(DiagnosticSink):
        def emit(self, event: DiagnosticEvent) -> None:
            received.append(event)

    sink = CaptureSink()
    obs = build_session_observability(Settings(), extra_sinks=[sink])
    obs.latency.mark("req-1", "runtime.received")
    obs.latency.mark("req-1", "executor.completed")
    obs.latency.finish("req-1", outcome="completed")

    latency_events = [e for e in received if e.event_name == "turn.latency"]
    assert len(latency_events) == 1
    assert latency_events[0].request_id == "req-1"
