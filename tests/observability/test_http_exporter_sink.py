import asyncio
import pytest

from newbro.observability.schema import DiagnosticEvent
from newbro.observability.sinks.http_exporter import HttpExporterSink

pytestmark = pytest.mark.anyio


def _latency_event(total_ms=4700):
    return DiagnosticEvent(
        level="INFO", event_name="turn.latency", component="runtime",
        summary="turn latency", request_id="r-1",
        details={"total_ms": total_ms, "steps": {"ttft": 3100, "stream": 1100}},
    )


class _Poster:
    def __init__(self):
        self.batches = []
        self.fail_times = 0

    async def __call__(self, url, headers, payload):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("boom")
        self.batches.append((url, headers, payload))


async def test_ignores_non_latency_events():
    poster = _Poster()
    sink = HttpExporterSink(url="http://x", headers={}, post=poster, event_name="turn.latency")
    sink.emit(DiagnosticEvent(level="INFO", event_name="other", component="x", summary="s"))
    await sink.aclose()
    assert poster.batches == []


async def test_batches_and_posts_on_flush():
    poster = _Poster()
    sink = HttpExporterSink(url="http://x", headers={"Authorization": "Bearer t"},
                            post=poster, event_name="turn.latency", batch_size=2)
    await sink.start()
    sink.emit(_latency_event(1))
    sink.emit(_latency_event(2))  # reaches batch_size -> flush
    await sink.drain()
    await sink.aclose()
    assert len(poster.batches) == 1
    url, headers, payload = poster.batches[0]
    assert url == "http://x" and headers["Authorization"] == "Bearer t"
    assert [p["total_ms"] for p in payload] == [1, 2]
    assert payload[0]["event"] == "turn.latency" and payload[0]["request_id"] == "r-1"
    assert payload[0]["steps"] == {"ttft": 3100, "stream": 1100}


async def test_overflow_drops_oldest():
    poster = _Poster()
    sink = HttpExporterSink(url="http://x", headers={}, post=poster,
                            event_name="turn.latency", batch_size=999, queue_max=2)
    for i in range(5):
        sink.emit(_latency_event(i))
    assert sink.dropped >= 3
    await sink.aclose()


async def test_retries_then_drops():
    poster = _Poster(); poster.fail_times = 10
    sink = HttpExporterSink(url="http://x", headers={}, post=poster,
                            event_name="turn.latency", batch_size=1, max_retries=2, retry_base=0.0)
    await sink.start()
    sink.emit(_latency_event(1))
    await sink.drain()
    await sink.aclose()
    assert poster.batches == []  # dropped after retries; no crash


async def test_disabled_when_no_url_is_noop():
    sink = HttpExporterSink(url=None, headers={}, post=None, event_name="turn.latency")
    sink.emit(_latency_event(1))  # must not raise
    await sink.aclose()
