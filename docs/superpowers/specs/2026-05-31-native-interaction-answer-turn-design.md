# Record native interaction answers as canonical user turns

Date: 2026-05-31
Status: Design (approved for spec review)

## Problem

When a user answers an intermediate codex plan-proposal question (e.g. selecting
Style / Language / Length), the answer ("Style: …; Language: …; Length: …") shows as a
user bubble **pinned to the bottom** of the thread, out of order, and **vanishes on
reload**.

Root cause: plan-proposal resolutions take two paths in
`session.resolve_interaction_request`:

- **Outbound follow-up** (`_spawn_outbound_follow_up_from_interaction`) re-submits a text
  instruction via `submit_executor_text_instruction`, which creates a canonical timeline
  turn. This is why the final **"Implement it"** approval persists as a real turn.
- **Native** (`_respond_to_native_interaction_request`, used for intermediate answers while
  the codex session is still live) sends the answer to codex and **returns early**
  (`session.py:4744-4746`) without recording any user turn — and ignores the
  `client_request_id` / `user_visible_text` it received.

So the intermediate answer only exists as the frontend's optimistic local turn.
`buildTimelineTurns` renders `[...canonical, ...optimistic]`, so an unreconciled optimistic
turn always sorts last; and since it's local-only, it disappears on reload.

Confirmed from a live snapshot: none of the 25 canonical turns is the "Style: …" answer, and
codex's own history does not surface it either (so there is no duplication risk).

## Goal

Record the user's native-interaction answer as a canonical user timeline turn so it
reconciles with the optimistic turn, sorts into its correct chronological place, and persists
across reloads — matching how "Implement it" already behaves.

## Non-goals

- No frontend change. `_sort_timeline_turns` already orders by `created_at`, and
  `buildTimelineTurns` already dedups optimistic turns whose `id` matches a canonical
  `client_request_id`; a correctly-recorded turn satisfies both.
- No change to the outbound-follow-up path (already records its turn).

## Design

### Record point (`session.resolve_interaction_request`, native branch)

The native branch currently is:

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

Add, immediately after the `put_interaction_request(...)` call (before the `task_id`
branch), a call to record the answer turn when a visible text is present:

```python
            self._record_interaction_answer_turn(
                resolution.request,
                user_visible_text=user_visible_text,
                client_request_id=client_request_id,
            )
```

### New helper `_record_interaction_answer_turn`

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
            assistant=None,
            status="completed",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"source": "native_interaction_answer", "request_id": request.request_id},
        )
        self._upsert_bro_thread_executor_turn(turn)
```

`_upsert_bro_thread_executor_turn` puts it into `_bro_thread_executor_turns`, which feeds
`_bro_thread_executor_turn_snapshot()` → `_build_bro_timeline_projection` (merge + sort). The
turn has a unique `turn_id` and no executor identity, so it appends and then sorts by
`created_at`.

### Why this works

- **Order:** `_sort_timeline_turns` keys on `created_at`; the answer's `created_at = now`
  (the resolve time) sorts it between the question turn and the later "Implement it" turn.
- **Reconcile:** the recorded turn carries `client_request_id`, which the frontend's
  `buildTimelineTurns` adds to `canonicalClientIds`, dropping the matching optimistic turn so
  it renders once, in place.
- **Persist:** it is a canonical snapshot turn, so it survives reloads.

## Edge cases

- No `user_visible_text` (other native interactions) → no turn recorded (early return).
- Missing `target_thread_id`/`persona_id` in `request.details` → skip (don't fabricate).
- Deny action ("Keep planning") carries a `user_visible_text` too (the frontend sends it);
  recording it is correct and consistent — it shows the user's "keep planning" turn in order.
- No duplication with codex history (codex does not surface the answer; verified).

## Testing

Runtime test (`tests/unit/runtime/test_session_runtime.py`):
- Put a `PLAN_PROPOSAL` `InteractionRequest` whose `details` has `persona_id` +
  `target_thread_id`. Monkeypatch `session.executor_node_manager.supply_interaction_response`
  to return `True` so `_respond_to_native_interaction_request` takes the native branch (and
  ensure `interaction_manager` can resolve the request).
- Call `session.resolve_interaction_request(request_id, action="approve",
  answer_text="…", user_visible_text="Style: Product brief; Language: English",
  client_request_id="plan-answer-1", answers={...})`.
- Assert `snapshot.bro_timeline_turns` contains exactly one turn whose `user.text` is the
  visible text, with `client_request_id == "plan-answer-1"` and a non-null `created_at`.

## Affected files

- `src/newbro/runtime/session.py` — native-branch call + `_record_interaction_answer_turn`
  helper.
- `tests/unit/runtime/test_session_runtime.py` — native-answer-records-turn test.
