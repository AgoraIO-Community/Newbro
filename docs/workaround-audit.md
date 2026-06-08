# Workaround And Fallback Audit

Date: 2026-05-29

## Scope And Commands

Generated/vendor paths excluded:

- `clients/web/node_modules/**`
- `clients/web/vendor/**`
- `clients/web/bun.lock`
- `clients/web/package-lock.json`

Commands run:

```bash
rg -n --glob '!clients/web/node_modules/**' --glob '!clients/web/vendor/**' --glob '!clients/web/bun.lock' --glob '!clients/web/package-lock.json' "fallback|fall back|workaround|work around|best effort|best-effort|silently|ignore|ignored|except Exception|pass$|TODO|HACK|XXX|placeholder|dummy|fake|pretend|stub" src/newbro
rg -n --glob '!clients/web/node_modules/**' --glob '!clients/web/vendor/**' "RuntimeDecision|should_speak|error_code|reason_code|diagnostic|diagnostics|HTTPException|ValueError|raise RuntimeError|except|pass$" src/newbro
rg -n --glob '!clients/web/node_modules/**' --glob '!clients/web/vendor/**' "latest|active|default|mock|scripted|heuristic|keyword|timestamp|dedupe|suppress|swallow|no-op|noop" src/newbro
rg -n --glob '!clients/web/node_modules/**' --glob '!clients/web/vendor/**' "client_request_id|target_thread_id|resume_handle|timeline_error|source_kind|system_fallback|mock_safe|requires_executor_capability|capability" src/newbro
```

The same commands were run with `-l` to verify the file-level hit set.

## Classification Summary

| Area | Classification | Reason | Action |
| --- | --- | --- | --- |
| `src/newbro/execution/reconcile.py` exception aggregation and invalid resume handle parsing | Bad workaround | `asyncio.gather(..., return_exceptions=True)` ignored unexpected execution failures, and invalid executor resume handles were silently discarded. This hid runtime/executor contract failures. | Fixed. Unexpected executor exceptions and invalid resume handles now fail the task/run visibly with execution detail metadata. |
| `src/newbro/communication/brain.py` notification rendering fallback | Intentional fallback, previously under-observable | Summary fallback is useful for notifications when the model cannot render prose, but the failure was not recorded. | Fixed observability. Fallback now emits `comm.reply.failed` with `communication_model_failure`. |
| `src/newbro/runtime/session.py` message reply model failure fallback | Intentional fallback | User receives `FALLBACK_ASSISTANT_ERROR_MESSAGE`, stream emits `assistant_response_failed`, and diagnostics emit `comm.reply.failed`. | Keep. Already observable and tested by diagnostics timeline coverage. |
| `src/newbro/runtime/session.py` imported Codex thread history load failure | Intentional fallback | Opening a thread remains successful while `timeline_status=failed` and `timeline_error` expose the failure. | Keep. Matches stable Bro Detail timeline contract. |
| `src/newbro/runtime/session.py` selected Codex subscription stop/unsubscribe errors | Benign cleanup fallback | Best-effort unsubscribe during close/replacement logs status and should not block user thread switching. | Keep; not a fake success path for work execution. |
| `src/newbro/runtime/session.py` live partial draft exceptions | Intentional silent-to-user path with diagnostics | Partial updates are UI-first and silent; failures are logged and emit `comm.reply.failed`. | Keep. |
| `src/newbro/runtime/executor_node_manager.py` send failures for dispatch/follow-up/audio | Intentional explicit failure surface | Send failures disconnect the node and return false or raise, and callers surface API/runtime errors. | Keep; no fake success after dispatch failure. |
| `src/newbro/runtime/executor_node_manager.py` Codex thread list/read/subscribe timeouts | Intentional explicit error | Request futures are cleaned up and typed timeout/runtime errors are raised to callers. | Keep. |
| `src/newbro/api/ws/stream.py` websocket disconnect/cancel handling | Benign transport cleanup | Disconnects and cancellation are lifecycle cleanup, not hidden product failures. Invalid actions use `action_rejected` with stable error codes. | Keep. |
| `src/newbro/api/ws/executors.py` executor websocket disconnect handling | Benign transport cleanup | Control-channel disconnects trigger node disconnect cleanup. Invalid messages receive `AckMessage(ok=False)`. | Keep. |
| `src/newbro/connectors/base/transport.py` notification watcher websocket errors | Intentional lifecycle stop, now observable | The watcher exits on websocket failure, but now logs the failure instead of returning silently. | Fixed observability. |
| `src/newbro/connectors/base/bindings.py` speaker errors while delivering notifications | Intentional continue-after-failed-delivery, now observable | The watcher continues after one TTS delivery failure so later notifications can still be delivered, but now logs the failed delivery. | Fixed observability and tested. |
| `src/newbro/connectors/voice/agora_convoai/session_service.py` cleanup `stop_session` failures | Benign cleanup, now observable | Cleanup after failed activation should not mask the primary activation error, but cleanup failures must be logged. | Fixed warning logs and tested. |
| `src/newbro/communication/brain.py` local correction/stop/continue regexes | Intentional product behavior but high risk | Stable docs allow focused local handlers for task controls/corrections while warning against broad fake semantic parsers. These are scoped to control/correction phrases and tests cover behavior. | Keep unless a manual trace finds keyword behavior taking over free-form meaning. |
| `src/newbro/communication/tools/create_task.py` `mock_safe` gate | Intentional product guard | Mock executor use is blocked unless explicitly marked mock-safe. This prevents fake task success. | Keep. |
| `src/newbro/communication/prompts/*` fallback/mock wording | Intentional prompt policy | Prompt text instructs the model not to fake capability and to ask/clarify. | Keep. |
| `src/newbro/executors/adapters/mock/*` | Test/dev-only runtime adapter | Mock executor is an explicit registered adapter for tests/dev, not a hidden fallback when real capability is required. | Keep. |
| `src/newbro/executors/adapters/codex/*` and `src/newbro/executors/adapters/acpx/*` broad exception handling | Explicit executor error mapping | Adapter parse/runtime failures are converted to executor `FAILED` events or raised; non-matching stream frames are ignored as parser filtering rather than execution success. | Keep. |
| `src/newbro/executors/node/service.py` contextlib suppress during cancellation/close | Benign cleanup | Cancellation and websocket shutdown cleanup should not create fake execution success. Runtime command errors emit explicit error messages. | Keep. |
| `src/newbro/blackboard/backends/memory.py` best-effort snapshots | Benign implementation detail | In-memory reads are await-free snapshots; writes remain serialized and emit events. | Keep. |
| `src/newbro/yaml_support.py`, `config_home.py`, connector/node config loaders | Compatibility/dev tooling | YAML fallback and config migration errors are CLI/config concerns, not runtime fake-success paths; invalid config generally raises or warns. | Keep. |
| Frontend tests and UI placeholders under `clients/web/src/**` | Test-only or benign UI text | `stub`, `placeholder`, and ignored transcript test cases are fixture/UI terms, not hidden runtime fallback. | Keep. |
| Lockfiles, generated CSS, TS config | Benign/generated | Hits are words such as placeholder/default/ignore in build artifacts or styles. | Excluded from runtime classification. |

## Fixed Bad Workarounds

### Execution exceptions were ignored by reconcile

- Boundary: Execution Brain / executor adapter / blackboard state.
- Root cause: `ReconcileLoop.tick` used `asyncio.gather(..., return_exceptions=True)` and only collected string run ids. Unexpected exceptions from `_execute_task` could be discarded.
- Fix: `_execute_task` now catches execution exceptions at the owning boundary and writes failed task/run state, failed summary, execution detail metadata with `reason_code=execution_exception`, releases the binding, and releases the persona. The top-level gather no longer swallows exceptions from failures outside that boundary.
- Verification: `.venv/bin/python -m pytest tests/integration/execution_blackboard/test_tick_claims_and_runs.py`.

### Invalid executor resume handles were silently discarded

- Boundary: Executor adapter result -> Execution Brain session continuity.
- Root cause: `_sync_executor_session` caught every resume-handle validation error and set `session.latest_resume_handle = None`, hiding an executor contract violation.
- Fix: invalid resume handles now raise `RuntimeError("Executor returned an invalid resume handle.")`; the execution exception path fails the task/run visibly.
- Verification: `.venv/bin/python -m pytest tests/integration/execution_blackboard/test_tick_claims_and_runs.py`.

### Notification summary fallback lacked diagnostics

- Boundary: Communication Brain notification rendering -> diagnostics/conversation output.
- Root cause: notification rendering exceptions fell back to candidate summaries without recording the model failure.
- Fix: `emit_notification` now emits `comm.reply.failed` with `reason_code=communication_model_failure` before using the summary fallback.
- Verification: `.venv/bin/python -m pytest tests/unit/communication/test_brain.py`.

### Connector notification delivery failures were swallowed

- Boundary: Connector notification watcher -> voice speaker/TTS delivery.
- Root cause: websocket notification watcher exceptions returned silently, and per-notification speaker failures were swallowed with `continue`.
- Fix: notification watcher and speaker-delivery failures now log exceptions. The per-message speaker failure still continues intentionally so one failed notification does not permanently stop delivery.
- Verification: `.venv/bin/python -m pytest tests/unit/connectors/voice/test_session_service.py`.

### Connector activation cleanup failures were swallowed

- Boundary: Connector session activation cleanup -> primary activation error.
- Root cause: if binding finalization failed after ConvoAI activation, cleanup `stop_session` errors were swallowed.
- Fix: cleanup failures are logged while preserving the primary binding/finalization exception.
- Verification: `.venv/bin/python -m pytest tests/unit/connectors/voice/test_session_service.py`.

## High-Risk Flow Trace

| Flow | Current failure surface | Status |
| --- | --- | --- |
| user text message -> Communication Brain -> `RuntimeDecision` / task creation | API/websocket actions reject invalid payloads; model failures emit `comm.reply.failed`, append a system fallback message, and emit `assistant_response_failed`; task creation uses `mock_safe` gate. | Acceptable. |
| live/partial/final voice transcript -> `RuntimeDecision.should_speak` -> UI/TTS | Partial failures emit diagnostics and stay silent; final/draft failures return `RuntimeDecision` or stream rejection depending path. Connector delivery failures now log exceptions. | Acceptable. |
| task command mutation -> validation -> API error or task state | Websocket command path rejects ambiguous/missing references and unsupported commands with stable error codes; tool path returns in-band tool errors. | Acceptable. |
| executor selection/session creation -> missing capability / offline executor | Unknown executors fail task/summary; detached node unavailable produces `waiting_executor`; direct Bro text/audio raises explicit `ValueError`. | Improved by execution exception fix. |
| executor native event ingestion -> protocol projection / diagnostics | Unknown/unauthorized run and thread events return negative ACKs; selected-thread timeline upserts by executor identity. | Acceptable. |
| imported executor history open/read -> timeline state / visible error | Thread open succeeds while timeline status/error exposes read failure. | Acceptable intentional fallback. |
| blackboard write/read failure -> runtime snapshot / diagnostics | In-memory store writes are serialized; diagnostic loop records writes. No durable backend failure path exists yet. | Acceptable for current in-memory backend. |
| connector setup and session activation -> user-visible error state | Prepare/activate routes map config/runtime errors to HTTP errors; notification watcher/speaker failures and activation cleanup failures now log exceptions. | Acceptable. |
| frontend snapshot/message handling -> UI-visible failed/blocked/error state | Session client parses `action_rejected`, voice hook exposes error phase, Bro timeline exposes `timeline_error`. | Acceptable; no frontend behavior changed in this pass. |

## Verification Log

- `.venv/bin/python -m pytest tests/integration/execution_blackboard/test_tick_claims_and_runs.py` passed.
- `.venv/bin/python -m pytest tests/unit/communication/test_brain.py` passed after adding notification fallback diagnostics.
- `.venv/bin/python -m pytest tests/unit/connectors/voice/test_session_service.py` passed after adding connector notification delivery and activation cleanup logging.
- `git diff --check` passed.
- `.venv/bin/python -m pytest` passed: 466 tests.

## Remaining Work For Goal Completion

- No remaining verification blocker. Frontend tests/build were not run because this pass did not change frontend runtime behavior under `clients/web`.
