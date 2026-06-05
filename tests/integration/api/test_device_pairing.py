from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.runtime import Settings
from newbro.runtime.container import RuntimeContainer


def _build_app(tmp_path):
    app = create_app()
    app.state.runtime_container = RuntimeContainer(
        communication_model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="model_reply", reply_override="Noted.")}
        ),
        settings=Settings(),
    )
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    return app


@pytest.mark.anyio
async def test_device_pairing_full_flow(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Device starts pairing.
        start = await client.post("/api/devices/pair/start")
        assert start.status_code == 200
        body = start.json()
        device_code, user_code = body["device_code"], body["user_code"]
        assert body["interval"] == 2

        # Unclaimed poll is pending.
        pending = await client.post("/api/devices/pair/poll", json={"device_code": device_code})
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"

        # A logged-in web user claims the code.
        await app.state.public_auth_store.create_invite("invite-1")
        assert (await client.post("/api/auth/invites/redeem", json={"code": "invite-1"})).status_code == 200
        claim = await client.post("/api/devices/pair/claim", json={"user_code": user_code})
        assert claim.status_code == 200

        # Device poll now returns a usable token.
        claimed = await client.post("/api/devices/pair/poll", json={"device_code": device_code})
        assert claimed.json()["status"] == "claimed"
        token = claimed.json()["token"]
        assert token

        # Single delivery: a second poll no longer returns the token.
        second = await client.post("/api/devices/pair/poll", json={"device_code": device_code})
        assert second.json()["status"] == "claimed"
        assert second.json()["token"] is None

        # The token authenticates as the user (bootstrap succeeds with the cookie).
        boot = await client.get("/api/me/bootstrap", cookies={"newbro_session": token})
        assert boot.status_code == 200


@pytest.mark.anyio
async def test_claim_requires_auth(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        start = (await client.post("/api/devices/pair/start")).json()
        resp = await client.post("/api/devices/pair/claim", json={"user_code": start["user_code"]})
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_poll_unknown_code_is_404(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/api/devices/pair/poll", json={"device_code": "bogus"})
        assert resp.status_code == 404


@pytest.mark.anyio
async def test_claim_unknown_code_is_404(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await app.state.public_auth_store.create_invite("invite-1")
        assert (await client.post("/api/auth/invites/redeem", json={"code": "invite-1"})).status_code == 200
        resp = await client.post("/api/devices/pair/claim", json={"user_code": "ZZZZ"})
        assert resp.status_code == 404
