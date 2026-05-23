from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from newbro.api.models import PersonaCreateRequest, PersonaUpdateRequest
from newbro.api.public_auth import PublicAuthError, require_session_owner

router = APIRouter()


@router.get("/sessions/{session_id}/personas")
async def list_personas(session_id: str, request: Request):
    user = await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    personas = await store.list_personas(user_id=user.user_id)
    await container.sync_user_personas(session_id=session_id, personas=personas)
    return personas


@router.post("/sessions/{session_id}/personas", status_code=201)
async def create_persona(
    session_id: str,
    body: PersonaCreateRequest,
    request: Request,
):
    user = await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Persona name is required.")
    if body.executor_node_id is not None and not await store.user_owns_executor_node(
        user_id=user.user_id,
        node_id=body.executor_node_id,
    ):
        raise HTTPException(status_code=400, detail=f"Executor node '{body.executor_node_id}' not found.")
    try:
        persona = await store.create_persona(
            user_id=user.user_id,
            name=body.name.strip(),
            avatar=body.avatar,
            base_prompt=body.base_prompt,
            executor_node_id=body.executor_node_id,
        )
    except PublicAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await container.sync_user_personas(
        session_id=session_id,
        personas=await store.list_personas(user_id=user.user_id),
    )
    return persona


@router.patch("/sessions/{session_id}/personas/{persona_id}")
async def update_persona(
    session_id: str,
    persona_id: str,
    body: PersonaUpdateRequest,
    request: Request,
):
    user = await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    personas = await store.list_personas(user_id=user.user_id)
    persona = next((item for item in personas if item.persona_id == persona_id), None)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found.")
    updates: dict[str, object] = {}
    if "name" in body.model_fields_set:
        if body.name is None or not body.name.strip():
            raise HTTPException(status_code=400, detail="Persona name is required.")
        updates["name"] = body.name.strip()
    if "avatar" in body.model_fields_set:
        if body.avatar is None:
            raise HTTPException(status_code=400, detail="Persona avatar is required.")
        updates["avatar"] = body.avatar
    if "base_prompt" in body.model_fields_set:
        if body.base_prompt is None:
            raise HTTPException(status_code=400, detail="Persona base prompt is required.")
        updates["base_prompt"] = body.base_prompt
    if "executor_node_id" in body.model_fields_set:
        if body.executor_node_id is not None and not await store.user_owns_executor_node(
            user_id=user.user_id,
            node_id=body.executor_node_id,
        ):
            raise HTTPException(status_code=400, detail=f"Executor node '{body.executor_node_id}' not found.")
        updates["executor_node_id"] = body.executor_node_id
        if body.executor_node_id != persona.executor_node_id:
            updates["bro_detail_session_id"] = f"bro-detail-{uuid4().hex[:8]}"
    if not updates:
        return persona
    try:
        updated = await store.update_persona(user_id=user.user_id, persona_id=persona_id, updates=updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found.") from exc
    except PublicAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updates:
        await container.sync_user_personas(
            session_id=session_id,
            personas=await store.list_personas(user_id=user.user_id),
        )
    return updated


@router.delete("/sessions/{session_id}/personas/{persona_id}")
async def delete_persona(
    session_id: str,
    persona_id: str,
    request: Request,
):
    user = await require_session_owner(request, session_id)
    container = request.app.state.runtime_container
    store = request.app.state.public_auth_store
    personas = await store.list_personas(user_id=user.user_id)
    persona = next((item for item in personas if item.persona_id == persona_id), None)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found.")
    if await container.persona_is_busy(persona_id):
        raise HTTPException(status_code=409, detail=f"Persona '{persona_id}' is busy and cannot be deleted.")
    await store.delete_persona(user_id=user.user_id, persona_id=persona_id)
    await container.sync_user_personas(
        session_id=session_id,
        personas=await store.list_personas(user_id=user.user_id),
    )
    return {"deleted": persona_id}
