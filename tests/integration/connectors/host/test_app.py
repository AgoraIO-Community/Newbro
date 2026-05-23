from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
import websockets

import newbro.connectors.host.app as connector_host_app_module
from newbro.connectors.host.app import create_app
from newbro.connectors.host.config import ConnectorHostSettings
from newbro.connectors.base import BaseConnectorModule, ConnectorModuleRegistry
from newbro.connectors.base.transport import HttpNewbroConnectorTransport
from newbro.connectors.voice.agora_convoai.module import create_headless_app
from newbro.connectors.voice.agora_convoai.service import AgoraSDKConvoAIService
from newbro.connectors.voice.agora_convoai.settings import AgoraConvoAIConnectorSettings


class FakeConnectorModule(BaseConnectorModule):
    slug = "agora-convoai"

    def build_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/connectors/agora-convoai/health")
        async def health() -> dict[str, object]:
            return {
                "status": "ok",
                "implementation_version": "agora-convoai-connector.v1",
                "sdk_loader_signature": ["agora_agent:Agent"],
                "upstream_transport_mode": "direct",
            }

        @router.post("/api/connectors/agora-convoai/sessions/prepare")
        async def prepare() -> dict[str, object]:
            return {"prepared": True}

        return router


@pytest.mark.anyio
async def test_connector_host_mounts_enabled_module_routes(monkeypatch):
    monkeypatch.setattr(
        connector_host_app_module,
        "create_connector_module_registry",
        lambda _enabled_modules: ConnectorModuleRegistry(modules=[FakeConnectorModule()]),
    )

    app = create_app(
        ConnectorHostSettings(
            enabled=True,
            enabled_connectors=["agora-convoai"],
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/connectors/agora-convoai/health")
        legacy_response = await client.get("/connectors/agora-convoai/health")

    assert response.status_code == 200
    assert legacy_response.status_code == 404
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["implementation_version"] == "agora-convoai-connector.v1"
    assert "agora_agent:Agent" in payload["sdk_loader_signature"]
    assert payload["upstream_transport_mode"] == "direct"


@pytest.mark.anyio
async def test_connector_host_skips_disabled_module_routes():
    app = create_app(
        ConnectorHostSettings(
            enabled=False,
            enabled_connectors=["agora-convoai"],
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        health_response = await client.get("/api/health")
        response = await client.get("/api/connectors/agora-convoai/health")
        legacy_health_response = await client.get("/health")

    assert health_response.status_code == 200
    assert health_response.json()["enabled"] is False
    assert health_response.json()["connectors"] == ["agora-convoai"]
    assert response.status_code == 404
    assert legacy_health_response.status_code == 404


@pytest.mark.anyio
async def test_connector_host_applies_cors_to_connector_routes(monkeypatch):
    monkeypatch.setattr(
        connector_host_app_module,
        "create_connector_module_registry",
        lambda _enabled_modules: ConnectorModuleRegistry(modules=[FakeConnectorModule()]),
    )

    app = create_app(
        ConnectorHostSettings(
            enabled=True,
            enabled_connectors=["agora-convoai"],
            cors_allowed_origins=["https://app.example.com"],
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/connectors/agora-convoai/sessions/prepare",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


def test_http_synapse_connector_transport_disables_proxy_env():
    transport = HttpNewbroConnectorTransport("http://127.0.0.1:8000")
    try:
        assert transport._http._trust_env is False
    finally:
        asyncio.run(transport.close())


@pytest.mark.anyio
async def test_http_synapse_connector_transport_passes_proxy_none_to_websockets(monkeypatch):
    captured: list[dict[str, object]] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self._messages = [
                json.dumps({"type": "snapshot"}),
                json.dumps({"type": "assistant_response_started", "request_id": "req-1"}),
                json.dumps(
                    {
                        "type": "assistant_response_completed",
                        "request_id": "req-1",
                        "reply_text": "Done.",
                    }
                ),
            ]

        async def recv(self):
            return self._messages.pop(0)

        async def send(self, _message: str):
            return None

    class FakeConnect:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_connect(uri, **kwargs):
        captured.append({"uri": uri, **kwargs})
        return FakeConnect()

    monkeypatch.setattr(websockets, "connect", fake_connect)

    transport = HttpNewbroConnectorTransport("http://127.0.0.1:8000")
    try:
        events = []
        async for event in transport.stream_message("session-1", "hello", request_id="req-1"):
            events.append(event)
        assert events[-1]["type"] == "assistant_response_completed"

        notifications = transport.watch_notification_texts("session-1")
        await notifications.aclose()
    finally:
        await transport.close()

    assert captured
    assert all(item["proxy"] is None for item in captured)


@pytest.mark.anyio
async def test_agora_connector_prepare_route_uses_real_loader_path_before_fake_sdk(monkeypatch):
    class FakeAsyncAgora:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def select_best_domain(self):
            return None

        def get_current_url(self):
            return "https://fake-convoai.local/api"

    class FakeArea:
        US = "US"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def with_stt(self, _vendor):
            return self

        def with_llm(self, _vendor):
            return self

        def with_tts(self, _vendor):
            return self

    class FakeAdvancedFeatures:
        def __init__(self, **kwargs):
            self.enable_rtm = kwargs.get("enable_rtm")

    class FakeSessionParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.data_channel = kwargs.get("data_channel")
            self.enable_metrics = kwargs.get("enable_metrics")
            self.enable_error_message = kwargs.get("enable_error_message")

    monkeypatch.setattr(
        AgoraSDKConvoAIService,
        "_load_sdk_types",
        lambda self: (
            FakeAsyncAgora,
            FakeArea,
            FakeAgent,
            object,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            FakeAdvancedFeatures,
            FakeSessionParams,
        ),
    )

    app = create_headless_app(
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="app-certificate",
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/connectors/agora-convoai/sessions/prepare",
            json={
                "profile": "VOICE",
                "channel_name": "demo-room",
                "display_name": "Tester",
                "user_uid": 101,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared_session_id"].startswith("prepared-")
    assert payload["app_id"] == "agora-app"
    assert payload["channel_name"] == "demo-room"


@pytest.mark.anyio
async def test_agora_connector_prepare_defaults_channel_name_to_synapse_session_id(monkeypatch):
    class FakeAsyncAgora:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def select_best_domain(self):
            return None

        def get_current_url(self):
            return "https://fake-convoai.local/api"

    class FakeArea:
        US = "US"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def with_stt(self, _vendor):
            return self

        def with_llm(self, _vendor):
            return self

        def with_tts(self, _vendor):
            return self

    class FakeAdvancedFeatures:
        def __init__(self, **kwargs):
            self.enable_rtm = kwargs.get("enable_rtm")

    class FakeSessionParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.data_channel = kwargs.get("data_channel")
            self.enable_metrics = kwargs.get("enable_metrics")
            self.enable_error_message = kwargs.get("enable_error_message")

    monkeypatch.setattr(
        AgoraSDKConvoAIService,
        "_load_sdk_types",
        lambda self: (
            FakeAsyncAgora,
            FakeArea,
            FakeAgent,
            object,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            FakeAdvancedFeatures,
            FakeSessionParams,
        ),
    )

    app = create_headless_app(
        AgoraConvoAIConnectorSettings(
            app_id="agora-app",
            app_certificate="app-certificate",
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/connectors/agora-convoai/sessions/prepare",
            json={
                "profile": "VOICE",
                "synapse_session_id": "session-1234",
                "display_name": "Tester",
                "user_uid": 101,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel_name"] == "session-1234"


@pytest.mark.anyio
async def test_agora_connector_activate_ignores_proxy_env_for_synapse_upstream(monkeypatch):
    class FakeTransport:
        def __init__(
            self,
            base_url: str,
            *,
            request_timeout_seconds: float = 10.0,
        ) -> None:
            self.base_url = base_url
            self.request_timeout_seconds = request_timeout_seconds
            self.created = 0

        async def create_session(self) -> str:
            self.created += 1
            return "session-1234"

        async def send_message(self, session_id: str, text: str):
            raise AssertionError("send_message should not be called during activate")

        async def submit_agora_event(self, session_id: str, event):
            return None

        async def stream_message(self, session_id: str, text: str, *, request_id: str):
            if False:
                yield None

        async def watch_notification_texts(self, session_id: str):
            if False:
                yield ""

        async def close(self) -> None:
            return None

    class FakeAsyncAgora:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def select_best_domain(self):
            return None

        def get_current_url(self):
            return "https://fake-convoai.local/api"

    class FakeArea:
        US = "US"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def with_stt(self, _vendor):
            return self

        def with_llm(self, _vendor):
            return self

        def with_tts(self, _vendor):
            return self

    class FakeAsyncAgentSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def start(self):
            return "runtime-session-1"

    class FakeAdvancedFeatures:
        def __init__(self, **kwargs):
            self.enable_rtm = kwargs.get("enable_rtm")

    class FakeSessionParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.data_channel = kwargs.get("data_channel")
            self.enable_metrics = kwargs.get("enable_metrics")
            self.enable_error_message = kwargs.get("enable_error_message")

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:9999")
    monkeypatch.setattr(
        "newbro.connectors.voice.agora_convoai.module.HttpNewbroConnectorTransport",
        FakeTransport,
    )
    monkeypatch.setattr(
        AgoraSDKConvoAIService,
        "_load_sdk_types",
        lambda self: (
            FakeAsyncAgora,
            FakeArea,
            FakeAgent,
            FakeAsyncAgentSession,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            FakeAdvancedFeatures,
            FakeSessionParams,
        ),
    )

    app = create_headless_app(
        AgoraConvoAIConnectorSettings(
            synapse_base_url="http://127.0.0.1:8000",
            app_id="agora-app",
            app_certificate="app-certificate",
            convoai_area="US",
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        prepared = await client.post(
            "/api/connectors/agora-convoai/sessions/prepare",
            json={
                "profile": "VOICE",
                "channel_name": "demo-room",
                "display_name": "Tester",
                "user_uid": 101,
            },
        )
        assert prepared.status_code == 200
        prepared_session_id = prepared.json()["prepared_session_id"]

        activated = await client.post(
            "/api/connectors/agora-convoai/sessions/activate",
            json={"prepared_session_id": prepared_session_id},
        )

    assert activated.status_code == 200
    payload = activated.json()
    assert payload["binding_id"].startswith("binding-")
    assert payload["synapse_session_id"] == "session-1234"
    assert payload["runtime_session_id"] == "runtime-session-1"


@pytest.mark.anyio
async def test_agora_connector_activate_reuses_existing_synapse_session_binding(monkeypatch):
    class FakeTransport:
        instances: list["FakeTransport"] = []

        def __init__(
            self,
            base_url: str,
            *,
            request_timeout_seconds: float = 10.0,
        ) -> None:
            self.base_url = base_url
            self.request_timeout_seconds = request_timeout_seconds
            self.created = 0
            self.__class__.instances.append(self)

        async def create_session(self) -> str:
            self.created += 1
            return "session-created-by-connector"

        async def send_message(self, session_id: str, text: str):
            raise AssertionError("send_message should not be called during activate")

        async def submit_agora_event(self, session_id: str, event):
            return None

        async def stream_message(self, session_id: str, text: str, *, request_id: str):
            if False:
                yield None

        async def watch_notification_texts(self, session_id: str):
            if False:
                yield ""

        async def close(self) -> None:
            return None

    class FakeAsyncAgora:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def select_best_domain(self):
            return None

        def get_current_url(self):
            return "https://fake-convoai.local/api"

    class FakeArea:
        US = "US"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def with_stt(self, _vendor):
            return self

        def with_llm(self, _vendor):
            return self

        def with_tts(self, _vendor):
            return self

    class FakeAsyncAgentSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def start(self):
            return "runtime-session-1"

    class FakeAdvancedFeatures:
        def __init__(self, **kwargs):
            self.enable_rtm = kwargs.get("enable_rtm")

    class FakeSessionParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.data_channel = kwargs.get("data_channel")
            self.enable_metrics = kwargs.get("enable_metrics")
            self.enable_error_message = kwargs.get("enable_error_message")

    monkeypatch.setattr(
        "newbro.connectors.voice.agora_convoai.module.HttpNewbroConnectorTransport",
        FakeTransport,
    )
    monkeypatch.setattr(
        AgoraSDKConvoAIService,
        "_load_sdk_types",
        lambda self: (
            FakeAsyncAgora,
            FakeArea,
            FakeAgent,
            FakeAsyncAgentSession,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            lambda **kwargs: None,
            FakeAdvancedFeatures,
            FakeSessionParams,
        ),
    )

    app = create_headless_app(
        AgoraConvoAIConnectorSettings(
            synapse_base_url="http://127.0.0.1:8000",
            app_id="agora-app",
            app_certificate="app-certificate",
            convoai_area="US",
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        prepared = await client.post(
            "/api/connectors/agora-convoai/sessions/prepare",
            json={
                "profile": "VOICE",
                "synapse_session_id": "session-existing",
                "display_name": "Tester",
                "user_uid": 101,
            },
        )
        assert prepared.status_code == 200
        assert prepared.json()["channel_name"] == "session-existing"
        prepared_session_id = prepared.json()["prepared_session_id"]

        activated = await client.post(
            "/api/connectors/agora-convoai/sessions/activate",
            json={"prepared_session_id": prepared_session_id},
        )

    assert activated.status_code == 200
    payload = activated.json()
    assert payload["binding_id"].startswith("binding-")
    assert payload["synapse_session_id"] == "session-existing"
    assert payload["channel_name"] == "session-existing"
    assert payload["runtime_session_id"] == "runtime-session-1"
    assert FakeTransport.instances
    assert FakeTransport.instances[0].created == 0
