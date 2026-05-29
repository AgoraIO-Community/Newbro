from __future__ import annotations

from typing import Any

from .jsonrpc import JsonRpcPeer


class CodexAppServerClient:
    def __init__(self, peer: JsonRpcPeer) -> None:
        self._peer = peer

    async def initialize(self) -> dict[str, object]:
        result = await self._peer.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "newbro-codex-executor",
                    "version": "0.1",
                },
                "capabilities": {
                    "experimentalApi": True,
                },
            },
        )
        await self._peer.notify("initialized", {})
        return _as_dict(result)

    async def get_account(self) -> dict[str, object]:
        result = await self._peer.request(
            "account/read",
            {"refreshToken": False},
        )
        return _as_dict(result)

    async def thread_start(
        self,
        *,
        cwd: str,
        approval_policy: str = "on-request",
        sandbox: str = "workspace-write",
    ) -> dict[str, object]:
        result = await self._peer.request(
            "thread/start",
            {
                "cwd": cwd,
                "approvalPolicy": approval_policy,
                "sandbox": sandbox,
            },
        )
        return _as_dict(result)

    async def thread_fork(
        self,
        *,
        thread_id: str,
        cwd: str,
        approval_policy: str = "on-request",
        sandbox: str = "workspace-write",
    ) -> dict[str, object]:
        result = await self._peer.request(
            "thread/fork",
            {
                "threadId": thread_id,
                "cwd": cwd,
                "approvalPolicy": approval_policy,
                "sandbox": sandbox,
            },
        )
        return _as_dict(result)

    async def thread_resume(
        self,
        *,
        thread_id: str,
    ) -> dict[str, object]:
        result = await self._peer.request(
            "thread/resume",
            {
                "threadId": thread_id,
            },
        )
        return _as_dict(result)

    async def thread_read(
        self,
        *,
        thread_id: str,
        include_turns: bool = True,
    ) -> dict[str, object]:
        result = await self._peer.request(
            "thread/read",
            {
                "threadId": thread_id,
                "includeTurns": include_turns,
            },
        )
        return _as_dict(result)

    async def thread_goal_get(self, *, thread_id: str) -> dict[str, object]:
        result = await self._peer.request(
            "thread/goal/get",
            {"threadId": thread_id},
        )
        return _as_dict(result)

    async def thread_turns_list(
        self,
        *,
        thread_id: str,
        limit: int | None = None,
        sort_direction: str | None = None,
        items_view: str | None = None,
    ) -> dict[str, object]:
        params: dict[str, object] = {"threadId": thread_id}
        if limit is not None:
            params["limit"] = limit
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        if items_view is not None:
            params["itemsView"] = items_view
        result = await self._peer.request("thread/turns/list", params)
        return _as_dict(result)

    async def thread_unsubscribe(
        self,
        *,
        thread_id: str,
    ) -> dict[str, object]:
        result = await self._peer.request(
            "thread/unsubscribe",
            {
                "threadId": thread_id,
            },
        )
        return _as_dict(result)

    async def thread_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_key: str | None = None,
        sort_direction: str | None = None,
    ) -> dict[str, object]:
        params: dict[str, object] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        if sort_key is not None:
            params["sortKey"] = sort_key
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        result = await self._peer.request("thread/list", params)
        return _as_dict(result)

    async def turn_start(
        self,
        *,
        thread_id: str,
        prompt: str,
    ) -> dict[str, object]:
        result = await self._peer.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": prompt,
                        "textElements": [],
                    }
                ],
            },
        )
        return _as_dict(result)

    async def next_event(self) -> dict[str, object]:
        return await self._peer.next_event()

    async def close(self) -> None:
        await self._peer.close()

    async def respond_to_request(
        self,
        *,
        request_id: object,
        method: str,
        params: dict[str, object],
        action: str,
        answer_text: str | None = None,
    ) -> None:
        await self._peer.respond(
            request_id,
            _build_request_response(
                method=method,
                params=params,
                action=action,
                answer_text=answer_text,
            ),
        )


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _build_request_response(
    *,
    method: str,
    params: dict[str, object],
    action: str,
    answer_text: str | None,
) -> dict[str, object]:
    normalized = method.lower()
    if normalized in {"item/commandexecution/requestapproval", "execcommandapproval"}:
        if action == "approve":
            amendment = params.get("proposedExecpolicyAmendment")
            if isinstance(amendment, list) and amendment and all(
                isinstance(item, str) for item in amendment
            ):
                return {
                    "decision": {
                        "acceptWithExecpolicyAmendment": {
                            "execpolicy_amendment": amendment,
                        }
                    }
                }
            return {"decision": "acceptForSession"}
        return {"decision": "decline"}
    if normalized in {"item/filechange/requestapproval", "applypatchapproval"}:
        return {"decision": "acceptForSession" if action == "approve" else "decline"}
    if normalized == "item/permissions/requestapproval":
        permissions = params.get("permissions")
        if not isinstance(permissions, dict):
            permissions = {}
        if action == "approve":
            return {"permissions": permissions, "scope": "session"}
        return {"permissions": {}, "scope": "turn"}
    if "user_input" in normalized or ("request" in normalized and "question" in normalized):
        answers: dict[str, object] = {}
        questions = params.get("questions")
        if isinstance(questions, list):
            for question in questions:
                if isinstance(question, dict):
                    question_id = question.get("id")
                    if isinstance(question_id, str) and question_id:
                        answers[question_id] = {"answers": [answer_text or ""]}
                        break
        return {"answers": answers}
    return {}
