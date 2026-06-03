from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from newbro.api.public_auth import require_session_owner
from newbro.api.workspace_path_tokens import extract_path_tokens
from newbro.runtime.executor_node_manager import (
    WorkspaceFileDenied,
    WorkspaceFileUnavailable,
)

router = APIRouter()

_CODE_TO_STATUS = {"denied": 403, "not_found": 404, "too_large": 413, "read_error": 502}


def _safe_filename(path: str) -> str:
    name = os.path.basename(path) or "download"
    return name.replace('"', "").replace("\n", "").replace("\r", "")


@router.get("/sessions/{session_id}/bro-threads/{thread_id}/turns/{turn_id}/file")
async def download_workspace_file(
    session_id: str,
    thread_id: str,
    turn_id: str,
    request: Request,
    path: str = Query(...),
) -> StreamingResponse:
    await require_session_owner(request, session_id)
    container = request.app.state.runtime_container

    try:
        session = container.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown_session") from exc

    snapshot = await session.snapshot()
    turn = next(
        (t for t in snapshot.bro_timeline_turns if t.turn_id == turn_id and t.thread_id == thread_id),
        None,
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="unknown_turn")

    assistant_text = turn.assistant.text if turn.assistant else None
    if path not in extract_path_tokens(assistant_text):
        # Gate 1: the path must be a token the assistant wrote in this turn.
        raise HTTPException(status_code=403, detail="path_not_in_turn")

    thread = next((th for th in snapshot.bro_threads if th.thread_id == thread_id), None)
    node_id = getattr(thread, "executor_node_id", None) if thread else None
    if node_id is None:
        node_id = container.executor_node_manager.node_id
    if node_id is None:
        raise HTTPException(status_code=504, detail="node_offline")

    agen = container.executor_node_manager.read_workspace_file(
        node_id=node_id,
        thread_id=thread_id,
        executor_thread_id=getattr(turn, "executor_thread_id", None),
        path=path,
    )
    # Pull the first item so Gate-2 failures map to an HTTP status *before* the
    # response body (and its 200 + headers) is committed.
    try:
        first = await agen.__anext__()
    except StopAsyncIteration:
        first = b""  # empty file: node sent eof with no chunks
    except WorkspaceFileDenied as exc:
        await agen.aclose()
        raise HTTPException(status_code=_CODE_TO_STATUS.get(exc.code, 502), detail=exc.code) from exc
    except WorkspaceFileUnavailable as exc:
        await agen.aclose()
        raise HTTPException(status_code=504, detail=exc.code) from exc

    async def body():
        yield first
        async for chunk in agen:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(path)}"'},
    )
