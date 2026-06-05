# Newbro Context

## Domain Terms

- **Direct Executor Interaction**: The current core product path where Bro Detail sends text or audio push-to-talk input directly to an executor, Codex first. Idle executor threads create `OutboundTurnRequest` records and start executor-native turns; active executor runs receive direct follow-up instructions. This path bypasses ordinary chat history and suppresses normal Communication notification candidates.
- **Direct Turn Starter**: The runtime module behind Direct Executor Interaction that owns the task-free no-active-run Codex turn lifecycle: create the `OutboundTurnRequest`, send executor-node `start_codex_turn`, transition the request to accepted or failed, and publish the updated session snapshot.
- **Bro Detail Thread Projection**: The runtime view that turns executor-native Codex threads, direct outbound turn requests, selected-thread subscriptions, and timeline events into Bro Detail thread and timeline state for the UI.
