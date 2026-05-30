from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from newbro.blackboard import BlackboardStore

from .base import ToolInputError


class ResolveInteractionRequestTool:
    name = "resolve_interaction_request"

    def __init__(
        self,
        store: BlackboardStore,
        *,
        apply_callback: Callable[..., Awaitable[list[str]] | list[str]] | None = None,
    ) -> None:
        self._store = store
        self._apply_callback = apply_callback

    def set_apply_callback(
        self,
        callback: Callable[..., Awaitable[list[str]] | list[str]] | None,
    ) -> None:
        self._apply_callback = callback

    async def __call__(
        self,
        *,
        request_id: str,
        action: str,
        answer_text: str | None = None,
        option_id: str | None = None,
        answers: dict[str, list[str]] | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        request = await self._store.get_interaction_request(request_id)
        if request is None:
            raise ToolInputError(
                "Interaction request not found.",
                code="interaction_request_not_found",
            )
        if self._apply_callback is None:
            raise ToolInputError(
                "Interaction request resolution is not configured.",
                code="interaction_resolution_unavailable",
            )
        try:
            callback_kwargs = {
                "action": action,
                "answer_text": answer_text,
                "option_id": option_id,
                "answers": answers,
                "reason": reason,
            }
            signature = inspect.signature(self._apply_callback)
            if not any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                callback_kwargs = {
                    key: value
                    for key, value in callback_kwargs.items()
                    if key in signature.parameters
                }
            maybe_awaitable = self._apply_callback(request_id, **callback_kwargs)
            affected_task_ids = (
                await maybe_awaitable if inspect.isawaitable(maybe_awaitable) else maybe_awaitable
            )
        except ValueError as exc:
            raise ToolInputError(str(exc), code="invalid_interaction_resolution") from exc
        except KeyError as exc:
            raise ToolInputError(str(exc), code="interaction_request_not_found") from exc
        return {
            "interaction_request": request,
            "affected_task_ids": list(affected_task_ids or []),
        }
