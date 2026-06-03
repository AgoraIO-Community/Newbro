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
                steps[name] = round((marks[end_step] - marks[start_step]) * 1000)
        end = marks.get("executor.completed") or max(marks.values(), default=turn.first_ts)
        total_ms = round((end - turn.first_ts) * 1000)
        self._emit(
            request_id=key,
            outcome=outcome,
            model_name=turn.model_name,
            total_ms=total_ms,
            steps=steps,
        )
