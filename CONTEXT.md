# Newbro Context

## Domain Terms

- **Executor Family**: A kind of background execution agent Newbro can run a node against — currently `codex`, `acpx`, and `hermes`. The canonical list lives in one place and is shared by the node registry, the CLI, and runtime settings.
- **Single-Family Node Invariant**: An Executor Node runs exactly one Executor Family. This is the product truth, enforced by the node registry and reflected by every node-creation path and local config writer. The lower-level run/node plumbing can build multiple families ("schemas stay multi-executor compatible"), but that is capability, not a supported product mode.
- **Probeable Family**: An Executor Family that has a meaningful local readiness probe (binary presence/version) — `codex` and `hermes`. `acpx` is run-only: it has no readiness probe and no start-readiness gate.
- **Direct Executor Interaction**: The current core product path where Bro Detail sends text or audio push-to-talk input directly to an executor, Codex first. Idle executor threads create `OutboundTurnRequest` records and start executor-native turns; active executor runs receive direct follow-up instructions. This path bypasses ordinary chat history and suppresses normal Communication notification candidates.
- **Direct Turn Starter**: The runtime module behind Direct Executor Interaction that owns the task-free no-active-run Codex turn lifecycle: create the `OutboundTurnRequest`, send executor-node `start_codex_turn`, transition the request to accepted or failed, and publish the updated session snapshot.
- **Bro Detail Thread Projection**: The runtime view that turns executor-native Codex threads, direct outbound turn requests, selected-thread subscriptions, and timeline events into Bro Detail thread and timeline state for the UI.
