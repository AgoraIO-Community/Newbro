from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from newbro.api.public_auth import PublicAuthError, PublicAuthStore, require_public_user

router = APIRouter()


class DevicePairStartResponse(BaseModel):
    device_code: str
    user_code: str
    interval: int
    expires_at: str


class DevicePairPollRequest(BaseModel):
    device_code: str


class DevicePairPollResponse(BaseModel):
    status: str
    token: str | None = None


class DevicePairClaimRequest(BaseModel):
    user_code: str


@router.post("/devices/pair/start", response_model=DevicePairStartResponse)
async def device_pair_start(request: Request) -> DevicePairStartResponse:
    store: PublicAuthStore = request.app.state.public_auth_store
    pairing = await store.create_device_pairing()
    return DevicePairStartResponse(
        device_code=pairing.device_code,
        user_code=pairing.user_code,
        interval=pairing.interval,
        expires_at=pairing.expires_at,
    )


@router.post("/devices/pair/poll", response_model=DevicePairPollResponse)
async def device_pair_poll(body: DevicePairPollRequest, request: Request) -> DevicePairPollResponse:
    store: PublicAuthStore = request.app.state.public_auth_store
    try:
        poll = await store.poll_device_pairing(device_code=body.device_code)
    except PublicAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DevicePairPollResponse(status=poll.status, token=poll.token)


class DevicePairClaimResponse(BaseModel):
    ok: bool


@router.post("/devices/pair/claim", response_model=DevicePairClaimResponse)
async def device_pair_claim(body: DevicePairClaimRequest, request: Request) -> DevicePairClaimResponse:
    user = await require_public_user(request)
    store: PublicAuthStore = request.app.state.public_auth_store
    try:
        await store.claim_device_pairing(user_code=body.user_code, user_id=user.user_id)
    except PublicAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DevicePairClaimResponse(ok=True)
