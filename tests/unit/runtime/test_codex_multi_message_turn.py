"""Regression lock for the codex multi-message turn contract.

A single codex turn streams several `agentMessage` items tagged with a `phase`:
`commentary` items are intermediate working narration (reasoning steps) and only
`final_answer` is the settled answer. These tests pin the invariants that we
repeatedly regressed while iterating:

  1. Commentary never settles the turn (status settles exactly once; no flicker).
  2. Commentary never fills the answer slot (only final_answer does).
  3. The final answer is not also recorded as a native reasoning step.

Test A replays the masked real-wire capture
(`docs/protocol/fixtures/codex-multi-message-turn-sample.jsonl`) so the contract
is checked against actual codex output, not a hand-built mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from newbro.protocol import (
    AgentResumeHandle,
    CodexThreadEventMessage,
    CodexTurnEventMessage,
    OutboundTurnRequest,
)
from newbro.runtime import Settings
from newbro.runtime.bro_detail_thread_projection import SelectedCodexThreadSubscription
from newbro.runtime.session import create_session_runtime
from tests.unit.runtime.test_session_runtime import ScriptedCommunicationModel, ScriptedPlan

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "docs/protocol/fixtures/codex-multi-message-turn-sample.jsonl"
)

_STREAMING = {"running", "pending"}


def _frames() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def _thread_payloads(frames: list[dict]) -> list[dict]:
    return [f["payload"] for f in frames if f.get("kind") == "codex_thread_event"]


def _model() -> ScriptedCommunicationModel:
    return ScriptedCommunicationModel(
        {"__default__": ScriptedPlan(conversational_act="request_clarification")}
    )


def test_fixture_exists_and_has_both_phases():
    payloads = _thread_payloads(_frames())
    phases = {
        item.get("phase")
        for p in payloads
        if isinstance((item := p.get("params", {}).get("item")), dict)
        and item.get("type") == "agentMessage"
    }
    assert "commentary" in phases
    assert "final_answer" in phases


@pytest.mark.anyio
async def test_real_wire_replay_commentary_never_settles_or_fills_answer():
    frames = _frames()
    payloads = _thread_payloads(frames)

    sample = next(p for p in payloads if p.get("method") == "item/completed")
    node = sample["node_id"]
    persona = sample["target_persona_id"]
    public_thread = sample["target_thread_id"]
    codex_thread = sample["thread_id"]
    subscription_id = sample["subscription_id"]
    session_id = sample["session_id"]

    final_turn_id = next(
        p["params"]["turnId"]
        for p in payloads
        if p.get("method") == "item/completed"
        and isinstance((item := p["params"].get("item")), dict)
        and item.get("type") == "agentMessage"
        and item.get("phase") == "final_answer"
    )

    session = create_session_runtime(session_id, model=_model(), settings=Settings())
    projection = session._bro_detail_thread_projection()
    projection.selected_codex_thread_subscriptions[persona] = SelectedCodexThreadSubscription(
        subscription_id=subscription_id,
        persona_id=persona,
        public_thread_id=public_thread,
        thread_continuity_key=public_thread,
        node_id=node,
        codex_thread_id=codex_thread,
        resume_handle=AgentResumeHandle(executor_id="codex", session_handle=codex_thread),
    )

    def answer_turn():
        turns = projection.bro_thread_executor_turns.get(public_thread) or []
        return next((t for t in turns if t.executor_turn_id == final_turn_id), None)

    transitions: list[str] = []
    final_seen = False
    for payload in payloads:
        item = payload.get("params", {}).get("item")
        if isinstance(item, dict) and item.get("phase") == "final_answer":
            final_seen = True
        await session.handle_codex_thread_event(CodexThreadEventMessage.model_validate(payload))
        turn = answer_turn()
        if turn is None:
            continue
        if not transitions or transitions[-1] != turn.status:
            transitions.append(turn.status)
        # Invariant 2: commentary must not populate the answer slot. Before any
        # final_answer item appears, the answer turn carries no assistant message.
        if not final_seen:
            assert turn.assistant is None, (
                f"commentary filled the answer slot before final_answer (status={turn.status})"
            )

    # Invariant 1: the turn settles exactly once — no completed -> running flip.
    seen_completed = False
    for status in transitions:
        if status == "completed":
            seen_completed = True
        elif seen_completed and status in _STREAMING:
            pytest.fail(f"turn un-settled (flicker) — status transitions: {transitions}")

    turn = answer_turn()
    assert turn is not None
    assert turn.status == "completed", f"final status was {turn.status!r}; transitions={transitions}"
    assert turn.assistant is not None and turn.assistant.text, "final answer missing at settle"


@pytest.mark.anyio
async def test_final_answer_progress_is_not_recorded_as_a_reasoning_step():
    """Invariant 3: commentary progress becomes a native reasoning step; the
    final answer is the answer bubble, never also a step."""
    session = create_session_runtime("session-1", model=_model(), settings=Settings())
    await session.blackboard.put_outbound_turn_request(
        OutboundTurnRequest(
            request_id="out-1",
            persona_id="forge",
            executor_id="codex",
            executor_node_id="node-forge",
            target_thread_id="thread-public",
            client_request_id="cr-1",
            input_modality="text",
            text="summarize",
            status="accepted",
            created_at="2026-06-05T00:00:00+00:00",
            updated_at="2026-06-05T00:00:00+00:00",
            metadata={"source": "bro_detail_text", "client_request_id": "cr-1"},
        )
    )

    def turn_event(phase: str, item_id: str, message: str) -> CodexTurnEventMessage:
        return CodexTurnEventMessage(
            request_id="out-1",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="thread-public",
            event_type="progress",
            message=message,
            executor_thread_id="codex-thread-1",
            executor_turn_id="turn-1",
            ok=True,
            metadata={"phase": phase, "codex_item_id": item_id},
        )

    await session.handle_codex_turn_event(turn_event("commentary", "c1", "Reading the devx docs"))
    await session.handle_codex_turn_event(turn_event("final_answer", "f1", "Here is the full report"))

    labels = [
        step.text
        for steps in session._recent_native_turn_reasoning().values()
        for step in steps
    ]
    assert "Reading the devx docs" in labels, "commentary should be a reasoning step"
    assert "Here is the full report" not in labels, "final answer must not be a reasoning step"
