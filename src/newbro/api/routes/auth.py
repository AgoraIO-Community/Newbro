from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from newbro.api.public_auth import (
    PublicAuthError,
    PublicUser,
    clear_public_session_cookie,
    require_public_user,
    set_public_session_cookie,
)


router = APIRouter()


class RedeemInviteRequest(BaseModel):
    code: str


class AuthMeResponse(BaseModel):
    user: PublicUser


class BootstrapResponse(BaseModel):
    user: PublicUser
    session_id: str
    default_persona_id: str
    default_bro_detail_session_id: str


@router.post("/auth/invites/redeem", response_model=AuthMeResponse)
async def redeem_invite(
    body: RedeemInviteRequest,
    request: Request,
    response: Response,
) -> AuthMeResponse:
    store = request.app.state.public_auth_store
    try:
        redeemed = await store.redeem_invite(body.code)
    except PublicAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_public_session_cookie(response, redeemed.raw_token)
    return AuthMeResponse(user=redeemed.user)


@router.get("/auth/me", response_model=AuthMeResponse)
async def get_me(request: Request) -> AuthMeResponse:
    return AuthMeResponse(user=await require_public_user(request))


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    store = request.app.state.public_auth_store
    await store.delete_browser_session(request.cookies.get("newbro_session"))
    clear_public_session_cookie(response)
    return {"ok": True}


@router.get("/me/bootstrap", response_model=BootstrapResponse)
async def bootstrap_public_user(request: Request) -> BootstrapResponse:
    user = await require_public_user(request)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    session = None
    for session_id in await store.owned_session_ids(user_id=user.user_id):
        try:
            session = container.get_session(session_id)
            break
        except KeyError:
            continue
    if session is None:
        session = container.create_session()
        await store.claim_session(user_id=user.user_id, session_id=session.session_id)
        session.observability.api.session_created(conversation_id=session.session_id)
    persona = await store.ensure_default_persona(user_id=user.user_id)
    await container.sync_user_personas(session_id=session.session_id, personas=[persona])
    session.set_voice_target(persona.persona_id)
    return BootstrapResponse(
        user=user,
        session_id=session.session_id,
        default_persona_id=persona.persona_id,
        default_bro_detail_session_id=persona.bro_detail_session_id,
    )
