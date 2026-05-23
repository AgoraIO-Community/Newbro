from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from newbro.communication.model import LlmTraceRecord

from ..logger import DiagnosticLogger


@dataclass(slots=True)
class CommunicationDiagnosticEmitter:
    logger: DiagnosticLogger
    llm_details: bool = False

    def message_received(self, *, conversation_id: str, user_text: str) -> None:
        self.logger.emit_event(
            level="INFO",
            event_name="comm.message.received",
            component="communication.brain",
            summary="Communication turn received",
            conversation_id=conversation_id,
            details={"user_text": user_text},
        )

    def interaction_classified(
        self,
        *,
        conversation_id: str,
        interaction_type: str,
        confidence: float,
        requires_user_decision: bool,
        importance: str,
        reason: str,
        control_action: str | None,
        task_mode: str | None,
    ) -> None:
        self.logger.emit_event(
            level="INFO",
            event_name="comm.interaction.classified",
            component="communication.interaction_classifier",
            summary="Interaction classified",
            conversation_id=conversation_id,
            outcome=interaction_type,
            details={
                "interaction_type": interaction_type,
                "confidence": confidence,
                "requires_user_decision": requires_user_decision,
                "importance": importance,
                "reason": reason,
                "control_action": control_action,
                "task_mode": task_mode,
            },
        )

    def tool_called(
        self,
        *,
        request_id: str | None,
        tool_name: str,
        status: str,
        args: dict[str, Any],
        result_summary: str | None,
        result_preview: dict[str, object] | None,
        affected_task_ids: list[str],
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.logger.emit_event(
            level="WARNING" if status == "failed" else "INFO",
            event_name="comm.tool.called",
            component="communication.tool_loop",
            summary="Communication tool call completed",
            request_id=request_id,
            task_id=affected_task_ids[0] if affected_task_ids else None,
            outcome=status,
            reason_code=error_code or ("tool_call_failed" if status == "failed" else None),
            details={
                "tool_name": tool_name,
                "args": args,
                "result_summary": result_summary,
                "result_preview": result_preview,
                "affected_task_ids": affected_task_ids,
                "error": (
                    {
                        "code": error_code or "tool_call_failed",
                        "message": error_message or "Tool call failed.",
                    }
                    if status == "failed"
                    else None
                ),
            },
        )

    def reply_generated(
        self,
        *,
        conversation_id: str,
        request_id: str | None,
        conversational_act: str,
        affected_task_ids: list[str],
        reply_text: str,
    ) -> None:
        self.logger.emit_event(
            level="INFO",
            event_name="comm.reply.generated",
            component="communication.brain",
            summary="Communication reply generated",
            conversation_id=conversation_id,
            request_id=request_id,
            task_id=affected_task_ids[0] if affected_task_ids else None,
            outcome=conversational_act,
            details={
                "affected_task_ids": affected_task_ids,
                "reply_text": reply_text,
            },
        )

    def reply_failed(
        self,
        *,
        conversation_id: str,
        request_id: str | None,
        reason_code: str,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if error_type is not None:
            details["error_type"] = error_type
        if error_message is not None:
            details["error_message"] = error_message
        self.logger.emit_event(
            level="ERROR",
            event_name="comm.reply.failed",
            component="communication.brain",
            summary="Communication reply generation failed",
            conversation_id=conversation_id,
            request_id=request_id,
            reason_code=reason_code,
            details=details,
        )

    def llm_trace(self, trace: LlmTraceRecord) -> None:
        self.logger.emit_event(
            level="INFO",
            event_name=_llm_event_name(trace.source, trace.phase),
            component="communication.llm",
            request_id=trace.request_id,
            task_id=trace.affected_task_ids[0] if trace.affected_task_ids else None,
            trace_id=trace.trace_id,
            summary="LLM interaction recorded",
            details=_llm_trace_details(trace, include_details=self.llm_details),
        )


def _llm_event_name(source: str, phase: str) -> str:
    prefix = "comm.llm" if source == "message" else "notify.llm"
    return prefix + (".request_built" if phase == "request_built" else ".response_completed")


def _llm_trace_details(trace: LlmTraceRecord, *, include_details: bool) -> dict[str, Any]:
    details: dict[str, Any] = {
        "source": trace.source,
        "phase": trace.phase,
        "prompt_sections": trace.prompt_sections,
        "available_tools": trace.available_tools,
        "tool_invocations": [
            {
                "tool_name": item.tool_name,
                "result_summary": item.result_summary,
            }
            for item in trace.tool_invocations
        ],
        "affected_task_ids": trace.affected_task_ids,
        "message_count": len(trace.messages),
        "notification_candidate_count": len(trace.notification_candidates),
    }
    if trace.source == "message" and trace.phase == "request_built":
        details["system_messages"] = [
            message
            for message in trace.messages
            if isinstance(message, dict) and message.get("role") == "system"
        ]
    if trace.source == "notification":
        details["notification_key_task_id"] = trace.notification_key_task_id
        details["notification_relevant_task_ids"] = trace.notification_relevant_task_ids
        details["notification_recent_chat_turn_count"] = trace.notification_recent_chat_turn_count
    if trace.user_text:
        details["user_text_preview"] = trace.user_text[:120]
    if trace.reply_text:
        details["reply_preview"] = trace.reply_text[:160]
    if include_details:
        details["user_text"] = trace.user_text
        details["reply_text"] = trace.reply_text
        details["messages"] = trace.messages
        details["notification_candidates"] = trace.notification_candidates
        details["tool_invocations"] = [
            {
                "tool_name": item.tool_name,
                "args": item.args,
                "result_summary": item.result_summary,
                "result_preview": item.result_preview,
            }
            for item in trace.tool_invocations
        ]
    return details
