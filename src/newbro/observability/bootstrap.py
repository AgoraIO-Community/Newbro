from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, TextIO

from .emitters import (
    ApiDiagnosticEmitter,
    BlackboardDiagnosticEmitter,
    CommunicationDiagnosticEmitter,
    ExecutionDiagnosticEmitter,
    NotificationDiagnosticEmitter,
)
from .latency import LatencyTracker
from .logger import DiagnosticLogger
from .schema import DiagnosticLevel, LEVEL_PRIORITY
from .sinks.pretty import PrettyDiagnosticSink
from .sinks.stdout import StdoutDiagnosticSink
from .store import InMemoryDiagnosticStore
from .sinks.types import DiagnosticSink

if TYPE_CHECKING:
    from newbro.runtime.config import Settings


@dataclass(slots=True)
class SessionObservability:
    store: InMemoryDiagnosticStore
    logger: DiagnosticLogger
    api: ApiDiagnosticEmitter
    blackboard: BlackboardDiagnosticEmitter
    communication: CommunicationDiagnosticEmitter
    execution: ExecutionDiagnosticEmitter
    notification: NotificationDiagnosticEmitter
    latency: LatencyTracker


def build_session_observability(
    settings: "Settings",
    *,
    extra_sinks: list[DiagnosticSink] | None = None,
) -> SessionObservability:
    store = InMemoryDiagnosticStore(max_events=settings.diagnostic_max_events)
    sinks = [build_stdout_sink(settings)]
    if extra_sinks:
        sinks.extend(extra_sinks)
    logger = DiagnosticLogger(
        store=store,
        sinks=sinks,
        min_level=_normalize_log_level(settings.log_level),
        app_version=_app_version(),
        git_sha=settings.git_sha,
        model_name=settings.openai_model if settings.openai_api_key else settings.communication_backend,
        settings_fingerprint=_settings_fingerprint(settings),
    )

    def _emit_turn_latency(*, request_id, outcome, model_name, total_ms, steps):
        logger.emit_event(
            level="INFO",
            event_name="turn.latency",
            component="runtime",
            summary=f"turn latency {total_ms}ms",
            outcome=outcome,
            request_id=request_id,
            details={"total_ms": total_ms, "steps": steps, "model_name": model_name},
        )

    latency = LatencyTracker(emit=_emit_turn_latency)

    return SessionObservability(
        store=store,
        logger=logger,
        api=ApiDiagnosticEmitter(logger),
        blackboard=BlackboardDiagnosticEmitter(logger),
        communication=CommunicationDiagnosticEmitter(logger, llm_details=settings.log_llm_details),
        execution=ExecutionDiagnosticEmitter(logger),
        notification=NotificationDiagnosticEmitter(logger),
        latency=latency,
    )


def _app_version() -> str | None:
    try:
        return metadata.version("newbro-cli")
    except metadata.PackageNotFoundError:
        return None


def _normalize_log_level(value: str) -> DiagnosticLevel:
    normalized = value.upper()
    if normalized in LEVEL_PRIORITY:
        return normalized  # type: ignore[return-value]
    return "INFO"


def build_stdout_sink(
    settings: "Settings",
    *,
    stream: TextIO | None = None,
) -> DiagnosticSink:
    target = stream or sys.stdout
    log_format = _normalize_log_format(settings.log_format)
    if log_format == "json":
        return StdoutDiagnosticSink(stream=target)
    if log_format == "pretty":
        return PrettyDiagnosticSink(
            stream=target,
            color_enabled=_should_enable_color(settings.log_color, stream=target),
        )
    if _is_readable_terminal(target):
        return PrettyDiagnosticSink(
            stream=target,
            color_enabled=_should_enable_color(settings.log_color, stream=target),
        )
    return StdoutDiagnosticSink(stream=target)


def _normalize_log_format(value: str) -> str:
    normalized = value.lower()
    if normalized in {"auto", "json", "pretty"}:
        return normalized
    return "auto"


def _normalize_log_color(value: str) -> str:
    normalized = value.lower()
    if normalized in {"auto", "always", "never"}:
        return normalized
    return "auto"


def _should_enable_color(value: str, *, stream: TextIO) -> bool:
    color = _normalize_log_color(value)
    if color == "always":
        return True
    if color == "never":
        return False
    return _is_readable_terminal(stream) and os.getenv("TERM", "").lower() != "dumb"


def _is_readable_terminal(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def _settings_fingerprint(settings: "Settings") -> str:
    payload = {
        "app_name": settings.app_name,
        "communication_backend": settings.communication_backend,
        "openai_model": settings.openai_model,
        "openai_timeout_seconds": settings.openai_timeout_seconds,
        "openai_base_url": settings.openai_base_url,
        "codex_executor_enabled": settings.codex_executor_enabled,
        "codex_command": settings.codex_command,
        "log_level": settings.log_level,
        "log_format": settings.log_format,
        "log_color": settings.log_color,
        "quiet_diagnostics_access_logs": settings.quiet_diagnostics_access_logs,
        "log_llm_details": settings.log_llm_details,
        "diagnostic_max_events": settings.diagnostic_max_events,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:12]


__all__ = ["SessionObservability", "build_session_observability"]
