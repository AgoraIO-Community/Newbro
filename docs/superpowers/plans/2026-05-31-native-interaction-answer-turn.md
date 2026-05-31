# Record Native Interaction Answers As Canonical Turns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a codex plan-proposal is resolved via the native path with a user-visible answer, record that answer as a canonical user timeline turn so it reconciles, orders by time, and persists across reloads.

**Architecture:** Backend-only. Add a `_record_interaction_answer_turn` helper that builds a user-only `BroTimelineTurn` (carrying the `client_request_id` and `created_at = now`) and upserts it via `_upsert_bro_thread_executor_turn`; call it from the native branch of `resolve_interaction_request`.

**Tech Stack:** Python 3.12 / Pydantic / pytest.

Spec: `docs/superpowers/specs/2026-05-31-native-interaction-answer-turn-design.md`

---

## File structure

- Modify: `src/newbro/runtime/session.py` — `_record_interaction_answer_turn` helper + a call in the native branch of `resolve_interaction_request`.
- Test: `tests/unit/runtime/test_session_runtime.py` — native-answer-records-turn test.

Test command: `.venv/bin/python -m pytest <path>::<test> -v`.

Facts confirmed:
- `session.py` already imports `BroTimelineTurn`, `BroTimelineMessage`, `InteractionRequest`, and `from datetime import UTC, datetime`.
- Required `BroTimelineTurn` fields: `turn_id, thread_id, persona_id, executor_id, owner` (rest default). Required `BroTimelineMessage` fields: `message_id, role` (rest default).
- A native resolution is forced in tests by monkeypatching `session.executor_node_manager.supply_interaction_response` to return `True` (it's awaited inside `_respond_to_native_interaction_request`, which then returns `True`).

---

## Task 1: Record the native answer as a canonical user turn

**Files:**
- Modify: `src/newbro/runtime/session.py`
- Test: `tests/unit/runtime/test_session_runtime.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/runtime/test_session_runtime.py` (all referenced symbols — `create_session_runtime`, `ScriptedCommunicationModel`, `ScriptedPlan`, `Settings`, `Persona`, `Task`, `TaskStatus`, `ExecutionSession as RuntimeExecutionSession`, `AgentResumeHandle`, `OutboundTurnRequest`, `CodexTurnEventMessage` — are already imported in this file):

```python
@pytest.mark.anyio
async def test_native_plan_answer_records_user_turn(monkeypatch: pytest.MonkeyPatch):
    session = create_session_runtime(
        "session-1",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )
    await session.blackboard.put_persona(
        Persona(
            persona_id="forge",
            name="Forge",
            avatar="bro",
            base_prompt="",
            executor_node_id="node-forge",
            bro_detail_session_id="detail-forge",
        )
    )
    await session.blackboard.put_task(
        Task(
            task_id="task-placeholder",
            root_task_id="task-placeholder",
            title="Done",
            goal="Done",
            status=TaskStatus.COMPLETED,
            preferred_executor="codex",
            metadata={"persona_id": "forge"},
        )
    )
    await session.blackboard.put_session(
        RuntimeExecutionSession(
            execution_session_id="exec-1",
            task_id="task-placeholder",
            base_executor_id="codex",
            executor_node_id="node-forge",
            continuity_key="thread-1",
            latest_resume_handle=AgentResumeHandle(
                executor_id="codex",
                session_handle="codex-thread-1",
            ),
        )
    )
    await session.blackboard.put_outbound_turn_request(
        OutboundTurnRequest(
            request_id="out-turn-q",
            persona_id="forge",
            executor_node_id="node-forge",
            target_thread_id="exec-1",
            text="Plan it",
            plan_mode=True,
            status="accepted",
        )
    )
    await session.handle_codex_turn_event(
        CodexTurnEventMessage(
            request_id="out-turn-q",
            node_id="node-forge",
            target_persona_id="forge",
            target_thread_id="exec-1",
            event_type="blocked",
            message="Pick the report style.",
            metadata={
                "thread_id": "native-thread-1",
                "prompt": "Pick the report style.",
                "interaction_kind": "plan_proposal",
                "blocked_method": "item/completed:plan",
                "proposal": {
                    "summary": "Pick the report style.",
                    "options": [
                        {"id": "approved_codex_plan", "label": "Run proposed plan", "letter": "A"},
                    ],
                },
            },
        )
    )
    pending = await session.blackboard.list_interaction_requests()
    assert len(pending) == 1
    interaction_request_id = pending[0].request_id

    async def fake_supply(*args, **kwargs):
        return True

    monkeypatch.setattr(session.executor_node_manager, "supply_interaction_response", fake_supply)

    await session.resolve_interaction_request(
        interaction_request_id,
        action="approve",
        option_id="approved_codex_plan",
        client_request_id="plan-answer-1",
        user_visible_text="Style: Product brief; Language: English",
    )

    snapshot = await session.snapshot(sync_imported_codex_threads=False)
    answer_turns = [
        t
        for t in snapshot.bro_timeline_turns
        if t.user is not None and t.user.text == "Style: Product brief; Language: English"
    ]
    assert len(answer_turns) == 1
    assert answer_turns[0].client_request_id == "plan-answer-1"
    assert answer_turns[0].created_at is not None
    assert answer_turns[0].thread_id == "exec-1"
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_native_plan_answer_records_user_turn -v`
Expected: FAIL — no answer turn is recorded today (`answer_turns` is empty, so `len(...) == 1` fails).

- [ ] **Step 3: Add the `_record_interaction_answer_turn` helper**

In `src/newbro/runtime/session.py`, add this method immediately AFTER the existing
`_record_native_turn_reasoning` method (they are siblings near `_upsert_bro_thread_executor_turn`):

```python
    def _record_interaction_answer_turn(
        self,
        request: InteractionRequest,
        *,
        user_visible_text: str | None,
        client_request_id: str | None,
    ) -> None:
        text = (user_visible_text or "").strip()
        if not text:
            return
        details = request.details or {}
        thread_id = details.get("target_thread_id")
        persona_id = details.get("persona_id")
        if not isinstance(thread_id, str) or not thread_id:
            return
        if not isinstance(persona_id, str) or not persona_id:
            return
        timestamp = datetime.now(tz=UTC).isoformat()
        stable_key = client_request_id or request.request_id
        turn = BroTimelineTurn(
            turn_id=f"{thread_id}:answer:{stable_key}",
            thread_id=thread_id,
            persona_id=persona_id,
            executor_id=request.executor_type or "codex",
            owner="executor",
            client_request_id=client_request_id,
            input_modality="text",
            user=BroTimelineMessage(
                message_id=f"{thread_id}:{stable_key}:user",
                role="user",
                kind="text",
                text=text,
                created_at=timestamp,
                updated_at=timestamp,
                status="completed",
                metadata={"source": "native_interaction_answer"},
            ),
            status="completed",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"source": "native_interaction_answer", "request_id": request.request_id},
        )
        self._upsert_bro_thread_executor_turn(turn)
```

- [ ] **Step 4: Call it from the native branch of `resolve_interaction_request`**

In `src/newbro/runtime/session.py`, find this exact block inside `resolve_interaction_request`:

```python
        if native_resolved:
            await self.blackboard.put_interaction_request(
                resolution.request.model_copy(update={"resume_strategy": "native_response"})
            )
            if resolution.request.task_id is None:
                await self.publish_snapshot(sync_imported_codex_threads=False)
                return []
            return [resolution.request.task_id]
```

Insert the recording call immediately after the `put_interaction_request(...)` statement and before the `if resolution.request.task_id is None:` line, so it reads:

```python
        if native_resolved:
            await self.blackboard.put_interaction_request(
                resolution.request.model_copy(update={"resume_strategy": "native_response"})
            )
            self._record_interaction_answer_turn(
                resolution.request,
                user_visible_text=user_visible_text,
                client_request_id=client_request_id,
            )
            if resolution.request.task_id is None:
                await self.publish_snapshot(sync_imported_codex_threads=False)
                return []
            return [resolution.request.task_id]
```

- [ ] **Step 5: Run the test, verify PASS**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_native_plan_answer_records_user_turn -v`
Expected: PASS

- [ ] **Step 6: Run the full runtime file (no regressions)**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/runtime/session.py tests/unit/runtime/test_session_runtime.py
git commit -m "feat: record native plan answers as canonical user turns"
```

---

## Final verification

- [ ] Backend: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -q` → all pass.
- [ ] Manual (`newbro dev`, restarted): answer a multi-question plan proposal; the answer turn
  appears in its correct chronological position (before "Implement it"), and survives a reload.

## Notes / gotchas

- `_record_interaction_answer_turn` only records when `user_visible_text` is non-empty and the
  request `details` carry `target_thread_id` + `persona_id` — other native interactions add
  nothing.
- The recorded turn carries `client_request_id`, which is what the frontend's
  `buildTimelineTurns` uses to drop the matching optimistic turn (reconciliation). `created_at`
  drives ordering via `_sort_timeline_turns`. No frontend change is needed.
- `owner="executor"` matches the codex-thread context (the existing native turns use the same);
  rendering keys off `turn.user`, not `owner`.
