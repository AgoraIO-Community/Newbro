"""Tests that the FastAPI lifespan starts and stops the latency exporter."""
from __future__ import annotations

import pytest
from contextlib import asynccontextmanager

from newbro.api.app import create_app
from newbro.runtime.config import Settings

pytestmark = pytest.mark.anyio


def test_no_exporter_when_disabled():
    """Container has no exporter when export is disabled (the default)."""
    settings = Settings(latency_export_enabled=False)
    app = create_app(settings=settings)
    container = app.state.runtime_container
    assert container.latency_exporter is None


def test_exporter_created_when_enabled():
    """Container holds an HttpExporterSink when export is enabled."""
    from newbro.observability.sinks.http_exporter import HttpExporterSink

    settings = Settings(
        latency_export_enabled=True,
        latency_export_url="http://example.com/events",
    )
    app = create_app(settings=settings)
    container = app.state.runtime_container
    assert isinstance(container.latency_exporter, HttpExporterSink)


async def test_lifespan_starts_and_stops_exporter():
    """Lifespan calls start() then aclose() on the exporter singleton."""
    calls: list[str] = []

    class _FakeSink:
        async def start(self):
            calls.append("start")

        async def aclose(self):
            calls.append("aclose")

    # Build the app with export disabled so real factory yields None,
    # then inject a fake exporter before the lifespan executes.
    settings = Settings(latency_export_enabled=False)
    app = create_app(settings=settings)
    fake_sink = _FakeSink()
    app.state.runtime_container.latency_exporter = fake_sink

    # Drive the lifespan directly by invoking the app's router lifespan context.
    # FastAPI exposes it via router.lifespan_context.
    async with app.router.lifespan_context(app):
        pass  # startup has run; shutdown runs on exit

    assert calls == ["start", "aclose"]
