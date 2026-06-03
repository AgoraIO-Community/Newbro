# Response Latency Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one consolidated `turn.latency` event per assistant response (a per-step waterfall) and ship those events to a configurable HTTP destination for filtering/dashboards.

**Architecture:** A per-session `LatencyTracker` records monotonic marks (reusing the existing `_record_direct_executor_text_metric` send-side boundaries + new executor-side marks in `handle_codex_turn_event`), computes named spans, and emits a `turn.latency` DiagnosticEvent. A process-wide, non-blocking `HttpExporterSink` batches those events and POSTs JSON to a configured URL (e.g. a Cloudflare Worker → Analytics Engine).

**Tech Stack:** Python 3.12, dataclasses, asyncio, httpx, Pytest (anyio). Cloudflare Workers (JS) for the example bridge.

**Spec:** `docs/superpowers/specs/2026-06-02-response-latency-observability-design.md`

---

## File Structure

- Create `src/newbro/observability/latency.py` — `LatencyTracker` (marks → named spans → emit). One responsibility: per-turn timing.
- Create `src/newbro/observability/sinks/http_exporter.py` — `HttpExporterSink` (non-blocking batch HTTP export). One responsibility: ship events off-box.
- Modify `src/newbro/runtime/config.py` — `Settings` export fields + env parsing.
- Modify `src/newbro/observability/bootstrap.py` — build the tracker into `SessionObservability`; accept a shared exporter sink.
- Modify `src/newbro/runtime/session.py` — forward send-side marks; add executor-side marks + `finish`.
- Modify the app/container startup — build the singleton exporter sink, start/stop it, inject into sessions.
- Create `cloudflare/latency-worker/{wrangler.toml,src/index.js,README.md}` and `docs/guides/response-latency.md`.

Run Python via `.venv/bin/python`. Work from `/Users/zhangqianze/Documents/Synopse`.

---

## Task 1: `LatencyTracker`

**Files:**
- Create: `src/newbro/observability/latency.py`
- Test: `tests/observability/test_latency_tracker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/observability/test_latency_tracker.py
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
```

If `tests/observability/` lacks `__init__.py` and sibling test dirs have them, mirror the convention.

- [ ] **Step 2: Run it, verify FAIL**

Run: `.venv/bin/python -m pytest tests/observability/test_latency_tracker.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/newbro/observability/latency.py
from __future__ import annotations

import logging
import time
from typing import Callable

LOGGER = logging.getLogger("runtime.latency")

# Named spans computed from mark pairs (end_step, start_step). A span is emitted
# only when both marks exist. Order here is the display order.
_SPANS: list[tuple[str, str, str]] = [
    ("executor_ready", "runtime.executor_ready", "runtime.received"),
    ("thread_resolved", "runtime.thread_resolved", "runtime.executor_ready"),
    ("active_execution_checked", "runtime.active_execution_checked", "runtime.thread_resolved"),
    ("outbound_turn_started", "runtime.outbound_turn_started", "runtime.active_execution_checked"),
    ("dispatch", "runtime.dispatch_completed", "runtime.outbound_turn_started"),
    ("publish", "runtime.snapshot_published", "runtime.dispatch_completed"),
    ("ttft", "executor.first_token", "runtime.dispatch_completed"),
    ("stream", "executor.completed", "executor.first_token"),
]


class _Turn:
    __slots__ = ("marks", "first_ts", "model_name")

    def __init__(self, ts: float) -> None:
        self.marks: dict[str, float] = {}
        self.first_ts: float = ts
        self.model_name: str | None = None


class LatencyTracker:
    """Per-turn latency accumulator. Best-effort: never raises into callers."""

    def __init__(
        self,
        *,
        emit: Callable[..., None],
        now: Callable[[], float] = time.monotonic,
        ttl_seconds: float = 120.0,
    ) -> None:
        self._emit = emit
        self._now = now
        self._ttl = ttl_seconds
        self._turns: dict[str, _Turn] = {}

    def mark(self, key: str | None, step: str, *, model_name: str | None = None) -> None:
        if not key:
            return
        try:
            now = self._now()
            turn = self._turns.get(key)
            if turn is None:
                turn = self._turns[key] = _Turn(now)
            turn.marks[step] = now
            if model_name:
                turn.model_name = model_name
            self._sweep(now)
        except Exception:  # pragma: no cover - best effort
            LOGGER.debug("latency mark failed", exc_info=True)

    def finish(self, key: str | None, *, outcome: str = "completed") -> None:
        if not key:
            return
        try:
            turn = self._turns.pop(key, None)
            if turn is None:
                return
            self._emit_turn(key, turn, outcome)
        except Exception:  # pragma: no cover - best effort
            LOGGER.debug("latency finish failed", exc_info=True)

    def _sweep(self, now: float) -> None:
        stale = [k for k, t in self._turns.items() if now - t.first_ts > self._ttl]
        for k in stale:
            turn = self._turns.pop(k, None)
            if turn is not None:
                self._emit_turn(k, turn, "incomplete")

    def _emit_turn(self, key: str, turn: _Turn, outcome: str) -> None:
        marks = turn.marks
        steps: dict[str, int] = {}
        for name, end_step, start_step in _SPANS:
            if end_step in marks and start_step in marks:
                steps[name] = int((marks[end_step] - marks[start_step]) * 1000)
        end = marks.get("executor.completed") or max(marks.values(), default=turn.first_ts)
        total_ms = int((end - turn.first_ts) * 1000)
        self._emit(
            request_id=key,
            outcome=outcome,
            model_name=turn.model_name,
            total_ms=total_ms,
            steps=steps,
        )
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `.venv/bin/python -m pytest tests/observability/test_latency_tracker.py -q`
Expected: 6 passed. (If a span value differs from the test's expectation, fix the test's expected number — do not weaken the span definition.)

- [ ] **Step 5: Commit**

```bash
git add src/newbro/observability/latency.py tests/observability/test_latency_tracker.py
git commit -m "feat(observability): LatencyTracker assembles per-turn latency from marks"
```

---

## Task 2: `HttpExporterSink`

**Files:**
- Create: `src/newbro/observability/sinks/http_exporter.py`
- Test: `tests/observability/test_http_exporter_sink.py`

The sink's `emit(event)` is synchronous and must never block; a background asyncio task batches and POSTs.

- [ ] **Step 1: Write the failing test**

```python
# tests/observability/test_http_exporter_sink.py
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
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `.venv/bin/python -m pytest tests/observability/test_http_exporter_sink.py -q`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/newbro/observability/sinks/http_exporter.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from ..schema import DiagnosticEvent
from .types import DiagnosticSink

LOGGER = logging.getLogger("runtime.latency_export")

Poster = Callable[[str, dict[str, str], list[dict[str, Any]]], Awaitable[None]]


def _record_from_event(event: DiagnosticEvent) -> dict[str, Any]:
    details = event.details or {}
    return {
        "event": event.event_name,
        "ts": event.ts.isoformat(),
        "request_id": event.request_id,
        "model_name": event.model_name,
        "outcome": event.outcome,
        "total_ms": details.get("total_ms"),
        "steps": details.get("steps", {}),
    }


class HttpExporterSink(DiagnosticSink):
    """Non-blocking: emit() enqueues; a background task batches and POSTs."""

    def __init__(
        self,
        *,
        url: str | None,
        headers: dict[str, str],
        post: Poster | None,
        event_name: str = "turn.latency",
        batch_size: int = 50,
        flush_seconds: float = 5.0,
        queue_max: int = 1000,
        max_retries: int = 3,
        retry_base: float = 0.5,
    ) -> None:
        self._url = url
        self._headers = headers
        self._post = post or _httpx_post
        self._event_name = event_name
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._queue_max = queue_max
        self._max_retries = max_retries
        self._retry_base = retry_base
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self.dropped = 0

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def emit(self, event: DiagnosticEvent) -> None:
        if not self.enabled or event.event_name != self._event_name:
            return
        if self._task is None:
            try:
                self.start_sync()
            except RuntimeError:
                return  # no running loop yet; drop (startup ordering)
        if self._queue.qsize() >= self._queue_max:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(_record_from_event(event))

    def start_sync(self) -> None:
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    async def start(self) -> None:
        if self._task is None and self.enabled:
            self.start_sync()

    async def drain(self) -> None:
        # test helper: let the background task process the queue
        await asyncio.sleep(0)
        while not self._queue.empty():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.01)

    async def aclose(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._closed:
            batch = await self._collect_batch()
            if batch:
                await self._flush(batch)

    async def _collect_batch(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=self._flush_seconds)
        except asyncio.TimeoutError:
            return batch
        batch.append(first)
        while len(batch) < self._batch_size and not self._queue.empty():
            batch.append(self._queue.get_nowait())
        return batch

    async def _flush(self, batch: list[dict[str, Any]]) -> None:
        delay = self._retry_base
        for attempt in range(self._max_retries + 1):
            try:
                await self._post(self._url, self._headers, batch)
                return
            except Exception:
                if attempt >= self._max_retries:
                    LOGGER.warning("latency export dropped %d events after retries", len(batch))
                    return
                await asyncio.sleep(delay)
                delay *= 2


async def _httpx_post(url: str, headers: dict[str, str], payload: list[dict[str, Any]]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `.venv/bin/python -m pytest tests/observability/test_http_exporter_sink.py -q`
Expected: 5 passed. If `drain()` timing flakes, the test sleeps are already generous; do not weaken assertions.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/observability/sinks/http_exporter.py tests/observability/test_http_exporter_sink.py
git commit -m "feat(observability): non-blocking HTTP exporter sink for latency events"
```

---

## Task 3: Settings + bootstrap wiring

**Files:**
- Modify: `src/newbro/runtime/config.py`
- Modify: `src/newbro/observability/bootstrap.py`
- Test: `tests/observability/test_bootstrap_latency.py`

- [ ] **Step 1: Add Settings fields**

In `src/newbro/runtime/config.py`, inside `@dataclass class Settings` (near `diagnostic_max_events`), add:
```python
    latency_export_enabled: bool = False
    latency_export_url: str | None = None
    latency_export_headers: tuple[tuple[str, str], ...] = ()
    latency_export_event_name: str = "turn.latency"
    latency_export_batch_size: int = 50
    latency_export_flush_seconds: float = 5.0
    latency_export_queue_max: int = 1000
```
(`headers` is a tuple-of-pairs so the dataclass stays hashable like `detached_executor_types`; convert to dict at use.)

In the env-loading function (where `diagnostic_max_events=int(os.getenv(...))` is set ~line 184), add:
```python
        latency_export_enabled=os.getenv("SYNAPSE_LATENCY_EXPORT_ENABLED", "false").lower() == "true",
        latency_export_url=os.getenv("SYNAPSE_LATENCY_EXPORT_URL") or None,
        latency_export_headers=_parse_headers(os.getenv("SYNAPSE_LATENCY_EXPORT_HEADERS")),
        latency_export_batch_size=int(os.getenv("SYNAPSE_LATENCY_EXPORT_BATCH_SIZE", "50")),
        latency_export_flush_seconds=float(os.getenv("SYNAPSE_LATENCY_EXPORT_FLUSH_SECONDS", "5")),
        latency_export_queue_max=int(os.getenv("SYNAPSE_LATENCY_EXPORT_QUEUE_MAX", "1000")),
```
And add a small helper near the other module helpers in `config.py`:
```python
def _parse_headers(raw: str | None) -> tuple[tuple[str, str], ...]:
    # "Authorization=Bearer x;X-Foo=bar" -> (("Authorization","Bearer x"),("X-Foo","bar"))
    if not raw:
        return ()
    pairs = []
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            pairs.append((k.strip(), v.strip()))
    return tuple(pairs)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/observability/test_bootstrap_latency.py
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
```

- [ ] **Step 3: Run it, verify FAIL**

Run: `.venv/bin/python -m pytest tests/observability/test_bootstrap_latency.py -q`
Expected: AttributeError (`SessionObservability` has no `latency`).

- [ ] **Step 4: Wire the tracker into bootstrap**

In `src/newbro/observability/bootstrap.py`:
(a) import: `from .latency import LatencyTracker`.
(b) Add `latency: LatencyTracker` to the `SessionObservability` dataclass.
(c) Allow a shared exporter sink to be injected, and build the tracker. Change `build_session_observability` signature to
`def build_session_observability(settings: "Settings", *, extra_sinks: list[DiagnosticSink] | None = None) -> SessionObservability:` and:
```python
    sinks: list[DiagnosticSink] = [build_stdout_sink(settings)]
    if extra_sinks:
        sinks.extend(extra_sinks)
    logger = DiagnosticLogger(store=store, sinks=sinks, min_level=_normalize_log_level(settings.log_level),
                              app_version=_app_version(), git_sha=settings.git_sha,
                              model_name=settings.openai_model if settings.openai_api_key else settings.communication_backend,
                              settings_fingerprint=_settings_fingerprint(settings))

    def _emit_turn_latency(*, request_id, outcome, model_name, total_ms, steps):
        logger.emit_event(
            level="INFO", event_name="turn.latency", component="runtime",
            summary=f"turn latency {total_ms}ms", outcome=outcome,
            request_id=request_id,
            details={"total_ms": total_ms, "steps": steps, "model_name": model_name},
        )

    latency = LatencyTracker(emit=_emit_turn_latency)
```
and pass `latency=latency` into the returned `SessionObservability(...)`.

- [ ] **Step 5: Run tests, verify PASS**

Run: `.venv/bin/python -m pytest tests/observability/test_bootstrap_latency.py -q`
Expected: 1 passed. Also `.venv/bin/python -m pytest tests/ -k observability -q` (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/config.py src/newbro/observability/bootstrap.py tests/observability/test_bootstrap_latency.py
git commit -m "feat(observability): wire LatencyTracker into session observability + settings"
```

---

## Task 4: Instrument the session (forward send-side marks + executor-side marks)

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/runtime/test_session_turn_latency.py` (light integration via the existing metric path)

- [ ] **Step 1: Orient**

Run:
- `grep -n "_record_direct_executor_text_metric\|handle_codex_turn_event\|find_session_by_outbound_turn_request\|_client_request_id_for_selected_thread_turn\|self.observability" src/newbro/runtime/session.py | head -40`
Read `_record_direct_executor_text_metric` (you'll forward from here) and `handle_codex_turn_event` (you'll add executor marks + finish here). Find how `handle_codex_turn_event` resolves the turn's `client_request_id` — `_client_request_id_for_selected_thread_turn` returns it for a codex turn event; reuse that.

- [ ] **Step 2: Forward send-side marks**

Inside `_record_direct_executor_text_metric`, after it computes `metric_details` and before/after the `emit_event` call, add:
```python
        self.observability.latency.mark(client_request_id, step)
```
This records every send-side step (`runtime.received … runtime.snapshot_published`) on the tracker with zero new scattered call sites.

- [ ] **Step 3: Add executor-side marks + finish**

In `handle_codex_turn_event(self, message)`, resolve the turn's client_request_id (use the existing helper, e.g. `crid = await self._client_request_id_for_selected_thread_turn(message)` — match its real name/signature from Step 1), then:
```python
        if crid:
            status = _timeline_status_from_codex_event(message)  # existing helper
            if message.... first event for this request:   # see note
                self.observability.latency.mark(crid, "executor.first_token",
                                                model_name=<model if available or None>)
            if status in {"completed", "failed", "cancelled"}:
                self.observability.latency.mark(crid, "executor.completed")
                self.observability.latency.finish(crid, outcome=status)
```
"first event for this request": the tracker's `mark` is idempotent per step (last-write-wins), so it is safe to call `mark(crid, "executor.first_token")` on **every** non-terminal event — the first timestamp is overwritten by later ones, which is wrong. To capture the FIRST token only, guard with a small per-session set: add `self._latency_first_token_seen: set[str] = set()` in `__init__`, and:
```python
            if crid not in self._latency_first_token_seen:
                self._latency_first_token_seen.add(crid)
                self.observability.latency.mark(crid, "executor.first_token", model_name=None)
            if status in {"completed", "failed", "cancelled"}:
                self.observability.latency.mark(crid, "executor.completed")
                self.observability.latency.finish(crid, outcome=status)
                self._latency_first_token_seen.discard(crid)
```
Keep all of this defensive: the tracker already swallows errors, but wrap the resolution in `try/except Exception: pass` so a latency hiccup never affects turn handling.

- [ ] **Step 4: Write a light integration test**

```python
# tests/runtime/test_session_turn_latency.py
import pytest
from newbro.observability.bootstrap import build_session_observability
from newbro.runtime.config import Settings

pytestmark = pytest.mark.anyio


def test_send_side_then_executor_marks_make_one_turn_latency():
    obs = build_session_observability(Settings())
    t = obs.latency
    # simulate the send-side metric forwarding
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
```
(A full end-to-end test through `handle_codex_turn_event` requires the heavy session harness; this verifies the assembled shape. The real wiring is exercised manually — see the final verification.)

- [ ] **Step 5: Run + verify**

Run: `.venv/bin/python -m pytest tests/runtime/test_session_turn_latency.py -q` → pass.
Run: `.venv/bin/python -c "import newbro.runtime.session"` → imports clean.
Run the existing session tests to check no regression: `.venv/bin/python -m pytest tests/ -k "session or runtime" -q` (note any PRE-EXISTING failures; only worry about new ones).

- [ ] **Step 6: Commit**

```bash
git add src/newbro/runtime/session.py tests/runtime/test_session_turn_latency.py
git commit -m "feat(runtime): record per-turn latency marks (send-side + executor TTFT/stream)"
```

---

## Task 5: Start the shared exporter at app startup

**Files:**
- Modify: the app/container startup (find with grep below)
- Test: covered by Task 2/3 unit tests; add a wiring smoke check

- [ ] **Step 1: Find where sessions/observability are built at app startup**

Run:
- `grep -rn "build_session_observability\|create_app\|lifespan\|runtime_container\|app.state" src/newbro/api/ src/newbro/runtime/container.py | head -30`
Identify (a) where `build_session_observability` is called and (b) the FastAPI `lifespan`/startup where a process-wide singleton can live and be started/stopped.

- [ ] **Step 2: Build the singleton exporter and inject it**

Add a helper in `src/newbro/observability/bootstrap.py`:
```python
def build_latency_exporter(settings: "Settings"):
    from .sinks.http_exporter import HttpExporterSink
    if not settings.latency_export_enabled or not settings.latency_export_url:
        return None
    return HttpExporterSink(
        url=settings.latency_export_url,
        headers=dict(settings.latency_export_headers),
        post=None,
        event_name=settings.latency_export_event_name,
        batch_size=settings.latency_export_batch_size,
        flush_seconds=settings.latency_export_flush_seconds,
        queue_max=settings.latency_export_queue_max,
    )
```
At app startup: create `exporter = build_latency_exporter(settings)` once, store it (e.g. on the runtime container / `app.state`), `await exporter.start()` in the lifespan startup and `await exporter.aclose()` on shutdown (guard for `None`). Pass it into every `build_session_observability(settings, extra_sinks=[exporter] if exporter else None)` call so all sessions' `turn.latency` events reach the one exporter.

- [ ] **Step 3: Verify**

Run: `.venv/bin/python -c "import newbro.api.app"` → builds.
Run: `.venv/bin/python -m pytest tests/ -k "observability or latency" -q` → pass.
Manual: with `SYNAPSE_LATENCY_EXPORT_ENABLED=true` and `SYNAPSE_LATENCY_EXPORT_URL` pointed at a local `nc -l`/test server, send a message and confirm a JSON batch arrives.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(api): start the latency HTTP exporter and inject it into sessions"
```

---

## Task 6: Cloudflare Worker bridge + docs

**Files:**
- Create: `cloudflare/latency-worker/wrangler.toml`, `cloudflare/latency-worker/src/index.js`, `cloudflare/latency-worker/README.md`
- Create: `docs/guides/response-latency.md`

- [ ] **Step 1: Write the Worker bridge**

`cloudflare/latency-worker/wrangler.toml`:
```toml
name = "newbro-latency"
main = "src/index.js"
compatibility_date = "2026-01-01"

[[analytics_engine_datasets]]
binding = "LATENCY"
dataset = "newbro_turn_latency"
```

`cloudflare/latency-worker/src/index.js`:
```js
export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("method", { status: 405 });
    if (req.headers.get("authorization") !== `Bearer ${env.INGEST_TOKEN}`)
      return new Response("unauthorized", { status: 401 });
    let events;
    try { events = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
    if (!Array.isArray(events)) events = [events];
    for (const e of events) {
      const s = e.steps ?? {};
      env.LATENCY.writeDataPoint({
        indexes: [String(e.model_name ?? "unknown")],
        blobs: [String(e.kind ?? ""), String(e.outcome ?? ""), String(e.request_id ?? "")],
        doubles: [
          Number(e.total_ms ?? 0), Number(s.executor_ready ?? 0), Number(s.dispatch ?? 0),
          Number(s.publish ?? 0), Number(s.ttft ?? 0), Number(s.stream ?? 0),
        ],
      });
    }
    return new Response("ok");
  },
};
```

`cloudflare/latency-worker/README.md`: deploy steps (`npx wrangler deploy`,
`npx wrangler secret put INGEST_TOKEN`), the `double1..6` → step mapping, and an
example SQL query (copy from the spec's Appendix A).

- [ ] **Step 2: Write the guide**

`docs/guides/response-latency.md`: how to enable export (the `SYNAPSE_LATENCY_EXPORT_*`
env vars), the `turn.latency` event/payload shape, that it also appears in stdout
logs and `GET /sessions/{id}/diagnostics/timeline?event_prefix=turn.latency`, and a
pointer to `cloudflare/latency-worker/` (or any HTTP ingest like Axiom).

- [ ] **Step 3: Commit**

```bash
git add cloudflare/latency-worker docs/guides/response-latency.md
git commit -m "docs: Cloudflare latency Worker bridge + response-latency guide"
```

---

## Final verification

- [ ] `.venv/bin/python -m pytest tests/observability/ tests/runtime/test_session_turn_latency.py -q` → all pass.
- [ ] `.venv/bin/python -c "import newbro.api.app"` → builds.
- [ ] Manual end-to-end: enable export to a local listener, send a message, confirm one `turn.latency` JSON record per response with `total_ms` and a `steps` map including `ttft`/`stream`; confirm a slow response shows the large step.

## Notes / scope

- V1 is the **text path** (`_record_direct_executor_text_metric` exists there). Audio
  (`submit_executor_audio_instruction` + a `transcribe` step) is a fast-follow using
  the same pattern.
- The exporter is process-wide and best-effort; if disabled, everything still lands
  in stdout logs and the queryable store.
