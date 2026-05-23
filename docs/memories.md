# Memories

Short log of important design decisions and changes for Newbro.

## 2026-04-04

- Established the concept-first architecture around `Communication Brain`, `Execution Brain`, `Shared Blackboard`, and protocol-first boundaries.
- Chose a backend-first FastAPI prototype with typed runtime, task, execution, conversation, and stream protocols.
- Defined V1 runtime scope as single-executor, while keeping schemas multi-executor compatible through task graph and executor identity fields.
- Used an in-memory blackboard and a generic mock executor to validate runtime flow before introducing real executors.
- Treated `docs/design.md` as the current architecture source of truth and `docs/memories.md` as the running decision log.
- Added a separate minimal `React + Vite + TypeScript` frontend workspace for experiencing the runtime through chat, task cards, and a live event feed.
- Renamed the backend Python package from `app/` to `runtime/` so the module path reflects the runtime role instead of a generic placeholder.
- Added explicit backend WebSocket runtime support and gated frontend message sending on the initial stream snapshot so the UI does not accept input before realtime is actually connected.
- Renamed key runtime files and variables toward the architecture language: `Action Router`, `Message Interpreter`, `Interaction Policy`, `Event-to-Response Mapper`, `Runtime State Store`, and `Executor Adapter Router`.
- Added a real OpenAI-backed path for `message_interpreter` and `response_generator`, with schema-strict interpretation and explicit fail-fast behavior when OpenAI is enabled but unavailable.
- Removed stub LLM mode from normal runtime behavior; OpenAI is now required for development/demo, while fake providers remain available only in tests.
- Added auto-loaded `.env.local` support plus `.env.example` so local runtime configuration no longer requires manual shell exports.
- Added a dedicated trace stream beside the main event stream so module-level causality can be inspected without mixing trace records into the product-facing runtime feed.
- Added a first-class conversation-only path with `chat_reply` so ordinary chat is no longer forced into `clarify`; clarification is now reserved for unresolved task/control intent.
- Added a generic external-executor integration layer plus an isolated Codex-backed executor adapter, while keeping the execution brain and transport on normalized executor protocols and exposing executor capabilities through session snapshots.
- Tightened `conversation-only` to social/meta chat only, routing capability-gated questions into normal executor tasks, and enriched response generation context so replies are authored from the agent’s perspective instead of echoing the user message.
- Switched task defaulting so Codex becomes the effective default executor when enabled, while completion replies prefer real executor result text over generic success status when available.
- Added a runtime guard so capability-gated questions are blocked with a clear explanation when only the mock executor is active, instead of producing misleading fake-success task flows.
- Simplified task creation so every `create_task` now requires a real executor, closing the hole where some LLM-produced tasks could still bypass the mock-executor guard.
- Added streamed response generation on the existing session websocket, with transient partial communication chunks updating one live assistant bubble while only the final communication event is persisted.
- Separated concise spoken-style communication from fuller task output, keeping task-board results sourced from artifacts while response generation summarizes them for TTS-friendly delivery.
- Added blackboard-backed message history for both message interpretation and response generation, capped at 30 persisted user/assistant messages and excluding transient stream chunks.
- Added LLM latency diagnostics to trace payloads, recording total request duration for normal calls and `ttfb_ms` for true streamed responses, while hiding transient `response_chunk` entries from the operator activity feed/export.
- Enriched `response_render_completed` so it now carries a nested `llm_response` summary with final rendered text plus duration and optional `ttfb_ms` when the response came from the LLM.
- Switched the Codex executor to `codex exec --json`, normalizing in-flight agent activity back into `ExecutionEvent` updates and keeping those mid-run updates transient on the execution stream instead of introducing a Codex-specific protocol surface.
- Tightened message interpretation so obvious social and subjective prompts such as feelings or opinion questions stay in `conversation_only`, while explicit executor-backed work requests still route to tasks even when phrased with a social opener.
- Reduced message-interpreter prompt size by replacing the full serialized session snapshot with compact interpreter context: only recent message history plus pending clarifications and executor capability summaries.
- Updated task graph construction to preserve an explicit `requires_executor_capability = false` override from the action bundle while still defaulting new tasks to real-executor requirements.
- Trimmed unnecessary interpreter JSON-schema fields so the model no longer has to fill redundant routing flags or runtime-owned create-task knobs on every action.
- Reshaped the interpreter Structured Outputs action schema into a lean single action object that stays OpenAI-compatible while still avoiding most redundant null-heavy padding fields.
- Added a stable prompt-cache key and shorter static interpreter instructions so repeated structured interpreter calls can reuse the same cached prompt prefix more effectively.
- Removed local semantic routing rewrites after `responses.parse()` so the interpreter now trusts the LLM's structured `conversation_only` / `task` / `clarification` result instead of reclassifying it in app code.
- Bound task-bearing user messages back to their resolved `task_id` in message history and changed terminal task replies to render from task-scoped history plus the originating user message, so unrelated later chat no longer pollutes a task's completion reply.
- Added fail-fast validation for interpreter-produced `create_task` actions so non-empty task goals are required, titles are derived only from valid goals, and malformed task payloads are rejected before blank tasks can enter the execution brain.
- Added a compact `active_tasks` summary to interpreter input, exposing only active task ids and goals so follow-up messages can better resolve to existing work without reintroducing the full session snapshot.
- Tightened `update_task` so it now requires a non-empty goal, and changed follow-ups against already-`done` tasks to fall back to creating a new task instead of restarting the completed one in place.

## 2026-04-06

- Tightened `control_task` so the communication tool surface accepts only canonical protocol command tokens such as `resume_task`, and invalid LLM-emitted aliases now round-trip through the OpenAI tool loop instead of crashing the message route.
- Switched the communication LLM path to a traditional OpenAI-compatible `chat.completions` loop that replays the local 30-message conversation history each turn instead of using Responses API conversation-state handles.
- Tightened executor selection so `create_task` rejects unknown `preferred_executor` ids and queued tasks with already-invalid executor ids now fail with a summary instead of crashing execution.
- Added a real Codex app-server executor path in `src/newbro`, wired runtime bootstrap to enable it via `SYNAPSE_CODEX_EXECUTOR_ENABLED`, and made Codex the default executor when enabled successfully while keeping mock available for explicit fallback and tests.
- Changed session message and command handling to schedule execution in a background loop instead of awaiting executor completion inline, so Codex-backed work no longer blocks the HTTP request path and snapshot updates flow over the existing session stream.
- Reused the session websocket as a bidirectional mixed stream, keeping snapshot/debug events while adding websocket `send_message` / `send_command` actions plus transient assistant-response events and hiding internal communication tool calls from the frontend transport.
- Reworked the communication tool surface around `add_task_note`, `add_constraint`, and `list_tasks`, removed silent latest-task fallback for ambiguous references, and added communication eval scaffolding for tool choice and spoken-reply quality regression checks.
- Added executor-availability context to the communication model and blocked capability-gated requests in mock-only mode, so requests like checking CPU usage no longer fall back to generic chat advice when no real executor is available.
- Added a repo-root `ARCHITECTURE.md` as the unified stable architecture overview and aligned the stable split docs to the same dual-brain, blackboard-centered target design.
- Unified Communication Brain around a task-first mental model with explicit mock-safe task creation, and added stable `TaskExecutionMode` blackboard projection with `undecided / lightweight / managed` classification.
- Added end-to-end proactive notification delivery with persisted `NotificationCandidate` projections, basic merge/defer policy, and emitted assistant updates written into user-visible conversation history.
- Narrowed `SessionSnapshot` to durable task/execution state only, and split durable conversation history plus debugger-oriented mutation/command/recent-write data into separate session projections and stream events.
- Added realtime-only `llm_trace` websocket events so the debugger UI can inspect LLM request/response payloads for normal message turns and proactive notification rendering without polluting durable projections.
- Enriched live `llm_trace` message payloads with tool invocation result summaries/previews and added a dedicated Tool Call History panel derived from those realtime trace events.
- Replaced derived Tool Call History with first-class realtime `tool_call` websocket events emitted from actual tool invocation attempts, including success/failure outcomes, so the debugger no longer reconstructs history from `llm_trace`.
- Added a diagnosis-first observability subsystem with canonical backend diagnostic events, correlation ids, reason codes, stdout JSON logging, and a per-session timeline API without changing the product-facing websocket stream contract.
- Added readable compact colorized console logs for observability when stdout is a terminal, while keeping JSON-line output when logs are redirected or piped.
- Removed the dedicated debug route and debugger-only websocket events, moving prompt/tool/blackboard inspection onto log-backed diagnostics timeline events while keeping the session websocket focused on assistant transport and durable snapshots.
- Quieted local access logs by filtering diagnostics timeline polling requests from `uvicorn.access` by default, and made the frontend diagnostics polling visibility-aware instead of polling continuously in hidden tabs.
- Removed the dedicated LLM trace UI and dropped backend prompt-trace diagnostic events, keeping tool-call and lifecycle logs as the main communication-side debugging surface.
- Restored backend-only LLM diagnostic events as summary logs by default, with verbose prompt/message payloads gated behind `SYNAPSE_LOG_LLM_DETAILS`, while leaving the dedicated LLM trace UI removed.

## 2026-04-07

- Tightened Communication Brain prompt policy so fact-checking, current-world information, and other live external-fact requests now default toward executor-backed `create_task` handling, with short clarifications for missing required details and no generic website/app fallback advice in mock-only mode.
- Focused notification LLM rendering on selected candidate-linked task context by adding structured recent-chat continuity, key-task, and relevant-task payloads, and added explicit diagnostics for adopted notification plans plus key-task/relevant-task selection on proactive updates.
- Tightened proactive notification wording so notification messages stay plain-text and spoken-style, explicitly avoiding markdown and list formatting in user-visible updates.

## 2026-04-08

- Added a standalone `examples/agora_conversational_ai` bridge that binds one live Agora Conversational AI agent to one Synapse session, exposes an OpenAI-compatible `/chat/completions` edge outside the main app, and reuses `conversation_appended` notification events to drive Agora `/speak` delivery for proactive updates only.
- Added a configurable frontend adapter and example-local React voice client under `examples/agora_conversational_ai`, so browser testing can start and stop Agora sample sessions through local normalized routes instead of binding the UI directly to an external sample-backend contract.
- Moved example auth and notification REST ownership fully to the external sample backend by storing `sample_session_id` in bridge bindings and proxying notification speech through a sample-backend speak route instead of using local auth-header env configuration.
- Collapsed `examples/agora_conversational_ai` into a single local backend using `agora-agent` plus local client-token generation, removed the separate sample-backend proxy model, and made `/frontend/session/start` / `/stop` own ConvoAI lifecycle directly inside this repo.

## 2026-04-12

- Switched `examples/agora_conversational_ai` to a bridge-first LLM path, reserving `bridge_session_id` before Agora activation and passing the public `/chat/completions` URL into the Agora SDK so live ConvoAI turns route through the bound local Synapse session instead of calling OpenAI directly from Agora.
- Reworked `examples/agora_conversational_ai` from an embedded-runtime example into an external bridge that creates and streams Synapse sessions through the main `8000` API server while keeping Agora lifecycle and the public custom-LLM callback on the separate `8010` bridge backend.

## 2026-04-13

- Renamed the public package, CLI, docs, env prefixes, and example bridge surface from `synopse` to `synapse`, and added a repo-root `synapse` bootstrap launcher plus a first-class Python CLI for setup, doctor, and local app startup.
- Split local bootstrap so `install.sh` now installs supported dev dependencies and repo packages, while `newbro setup` became an env-configuration wizard for the root `.env.local` with a non-interactive automation path.
- Added a separate headless gateway host plus first-party `src/newbro/gateways/` modules, promoted Agora ConvoAI into the new gateway module structure, and extended the CLI so gateway config can be prompted from `newbro setup` or `newbro gateway setup` and auto-started from `newbro dev` / `newbro start`.

## 2026-04-14

- Switched gateway host configuration to a shared `config/gateway.yaml` contract referenced by `SYNAPSE_GATEWAY_CONFIG_FILE`, renamed public gateway config naming from `modules` to `gateways`, and moved Agora ConvoAI ASR/TTS selection to YAML-backed managed or BYOK settings.
- Updated the Agora gateway prepare flow so frontend requests can override `agent_instructions`, `agent_greeting`, `agent_uid`, and `user_uid` per session while keeping the Synapse bridge-backed LLM path internal.
- Moved the live runtime env and gateway YAML out of the repo and into `~/.synapse/.env` plus `~/.synapse/config.yaml`, keeping repo files as setup templates only.
- Moved the main React/Vite frontend workspace from repo-root `frontend/` to `src/newbro/ui/`, while keeping `synapse frontend`, `newbro dev`, and `install.sh` wired to the new location.
- Moved the Agora example browser client from `examples/agora_conversational_ai/frontend/` to repo-root `exmaple-ui/` while keeping `src/newbro/ui/` as the main CLI-managed frontend workspace.
- Removed the CLI dependency on a tracked repo `.env.example` and moved the setup wizard to a code-defined env template while keeping `~/.synapse/.env` as the rendered config destination.
- Updated `install.sh` to create starter `~/.synapse/.env` and `~/.synapse/config.yaml` files during bootstrap without overwriting existing user config, leaving `newbro setup` for filling in real values afterward.
- Pinned Agora ConvoAI gateway setup to the `US` region, removed interactive prompts for token TTL and speak/request tuning, and changed the managed Minimax default voice to `English_magnetic_voiced_man`.
- Removed the legacy `examples/agora_conversational_ai` bridge package and its dedicated integration tests, leaving the first-party `src/newbro/gateways/agora_convoai/` gateway module plus repo-root `exmaple-ui/` as the supported Agora path.
- Added a first-class `synapse service` CLI for Ubuntu/systemd deployment from a repo checkout, installing one combined `newbro.service` unit that runs `newbro start` as the deploy user and keeps runtime config in `~/.synapse`.
- Allowed `synapse service install` to run as `root`, with the installed systemd unit now running as the invoking user and reading runtime config from that user’s `~/.synapse` home.
- Moved the Codex executor command path out of `SYNAPSE_CODEX_COMMAND` env and into `~/.synapse/config.yaml` under `runtime.codex_command`, while keeping `newbro setup` responsible for prompting and migrating the effective path.

## 2026-04-15

- Reworked the main frontend in `src/newbro/ui/` into a chat-first dual-pane workbench with `Conversation` on the left and `Workbench` on the right, keeping debug detail as a secondary surface instead of the primary layout.
- Upgraded the main frontend workspace to Vite 8, introduced TanStack Router and TanStack Query for frontend app structure and durable read-model state, and moved the session HTTP/WebSocket client code under `src/newbro/ui/src/lib/`.
- Added a documented `Frontend Workbench` guide under `docs/guides/` so the current main UI intent, stack, and data-flow boundaries are part of the stable docs.

## 2026-04-16

- Routed conversational `control_task` through runtime command application, so chat-driven cancel/pause updates now affect live executor runs and task projections instead of only appending blackboard command records.
- Suppressed pending notification candidates for cancelled tasks and ignored stale late completion events after cancellation so cancelled work no longer reappears as proactive assistant replies.
- Added structured task focus to internal communication history and grounded short stop/continue/current-work turns on that focus plus live blackboard state, so chat replies stop drifting onto the wrong task.
- Added a generic focused-bundle correction layer so short follow-up fixes like `it should be X`, `to X`, `from X`, and `X instead of Y` resolve against structured bundle slots, ask on ambiguity, and replace the whole bundle only when the correction is explicit enough.
- Shifted correction/current-work interpretation back toward the LLM by exposing focused bundle state in prompt context and using only a small post-tool grounding fallback in runtime instead of expanding local English heuristic parsing.
- Stopped rewriting the execution-mode blackboard projection when only `elapsed_seconds` changes, so `bb.execution_mode.updated` and `exec.task.classified` now fire on semantic mode transitions instead of spamming repeated `managed` updates.

## 2026-04-17

- Added configurable frontend transport base support through `VITE_API_BASE_URL`, plus backend `SYNAPSE_CORS_ALLOWED_ORIGINS`, so the main UI under `src/newbro/ui/` can be deployed on a separate public origin such as Vercel while keeping local same-origin behavior as the default.
- Added a first-party GitHub Actions Vercel deployment workflow for `src/newbro/ui/`, with pull-request previews and production deploys from `main`.

## 2026-04-18

- Documented the production Vercel UI deployment contract in stable docs, including `VITE_API_BASE_URL`, backend `SYNAPSE_CORS_ALLOWED_ORIGINS`, and the requirement for an HTTPS reverse proxy to preserve `/api/sessions` routing plus websocket upgrades to the main `8000` Synapse API.
- Updated the GitHub Actions Vercel production deploy to inject `VITE_API_BASE_URL=https://newbro.plutoless.com` during the build and accept `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` from Actions variables with secrets as a fallback, so merge-to-`main` deploys do not depend on one GitHub storage location for those IDs.
- Added dedicated gateway-host browser CORS config under `host.cors_allowed_origins` and updated the production deploy contract so deployed voice mode can call `/gateway/agora-convoai/*` on the same public server origin as text mode.
- Added a compact Agora voice accessory to the main frontend that starts and stops gateway-backed ConvoAI sessions through `/gateway/agora-convoai/*`, keeps the main text workbench session separate, and allows a distinct `VITE_GATEWAY_BASE_URL` for browser gateway calls.
- Reworked the main frontend voice path into a top-centered `Text` / `Voice` mode switch that recreates a fresh session on each mode change, rebinds the whole shell to the gateway-returned voice `synapse_session_id` while voice mode is active, and shows live Agora transcript turns in the left pane.
- Promoted the left-pane mode switch into a larger hero-adjacent control and changed the main frontend to boot into `Voice` mode by default instead of `Text`.
- Reworked voice mode so it now boots idle by default, uses an attached left-edge mode rail on desktop, and exposes explicit `Start` / `Stop` plus microphone `Mute` / `Unmute` controls before and during live voice interaction.
- Vendored `src/newbro/ui/vendor/agora-rtm/` and pointed the frontend workspace at that local package so plain `npm install` works on Vercel without `--legacy-peer-deps` despite the published Agora RTM package's incompatible peer declaration.
- Added `@rolldown/binding-linux-x64-gnu` as a root optional dependency in `src/newbro/ui/` so Vite 8 builds on Linux/Vercel do not fail when npm skips Rolldown's nested native binding package.

## 2026-04-21

- Added append-only `TaskExecutionDetailEntry` blackboard storage plus bounded communication-context injection for the 5 most recently detail-active tasks, with the last 20 execution-detail entries per included task.
- Extended `query_task_detail` to return bounded execution detail and command history, and added always-on `system_messages` audit logging on `comm.llm.request_built` for Communication Brain message turns.
- Filtered low-value Codex progress chatter out of task execution detail, made run/task projection writes change-aware, and demoted repetitive progress-refresh blackboard logs out of normal `INFO` output.
- Cut real executor runtime over to a detached executor-host process with a dedicated `/api/executors/control` websocket, keeping Synapse as the durable control plane while `mock` remains the only in-process executor.
- Added executor-node-aware execution state including `waiting_executor`, persisted `executor_node_id` on execution lineage/binding objects, opaque workspace ids for `session_affinity`, and dedicated `newbro executor setup` / `newbro executor run` CLI flows.

## 2026-04-22

- Removed detached executor host-token auth and the unused control-channel heartbeat from the adopted V1 contract, leaving websocket connect/disconnect as the only liveness signal.
- Made detached-executor enablement and executor-family selection control-plane config under `newbro setup`, while `newbro executor setup` now owns only executor-side host config and generates a stable local `node_id`.
- Changed `newbro start` / systemd deployment so the main FastAPI origin now serves the built frontend UI from `/`, while same-origin `/gateway/...` requests are proxied back to the separate gateway host.
- Replaced the adopted Caddy-based `newbro start` front door with an in-repo `newbro.edge` transport layer that serves the built UI and proxies API, websocket, and gateway traffic to internal backend and gateway listeners.
- Made detached executor host foreground lifecycle explicit so `newbro executor run` now prints start, connect, ready, disconnect, retry, and interrupt state instead of failing silently during control-channel connection issues.
- Merged the temporary `newbro.edge` transport back into the main Synapse service so `newbro start` now runs one public service process that serves the built UI, exposes `/api/sessions` and `/api/executors/control`, and mounts enabled `/gateway/...` routes directly.
- Renamed the executor substrate packages to `src/newbro/executors/{core,adapters,host}`, moved connector runtime code under `src/newbro/connectors/{base,host,voice/...}`, and renamed the public connector contract to `connector_host`, `connectors`, `SYNAPSE_CONNECTOR_*`, `VITE_CONNECTOR_BASE_URL`, `synapse connector ...`, and `/api/connectors/...`.
- Renamed the detached executor worker contract from `host` to `node`, moving code under `src/newbro/executors/node` and renaming the current executor control-plane fields to `executor_node`, `executor_node_id`, and `node_id`.

## 2026-04-23

- Moved the adopted public runtime contract under `/api/*`, including session HTTP routes, connector routes, health/OpenAPI/docs endpoints, and both websocket paths, so frontend-serving origins can proxy all non-frontend traffic with a single `/api/` rule.
- Replaced the main frontend root shell with a componentized `Newbro` command-center concept layout, using a light persona-to-card adapter with seeded sample fallbacks instead of the prior live workbench root experience.
- Wired the `Newbro` shell's `Interaction memory` panel to live Agora transcript state, with explicit top-bar start/stop/mute controls, shell rebinding to the gateway-backed voice `synapse_session_id`, and retained transcript history after stop.
- Added operator-managed executor-node CRUD with issued node-token enrollment, per-Bro `executor_node_id` binding, derived Bro liveness from the bound node's live control-channel connection state, and a copyable `newbro executor run --base-url ... --node-id ... --token ...` connect command in the UI.
- Removed the local `executor_node.enabled` gate and made `newbro executor run` reuse the local executor setup flow automatically when executor-family or command-path config is missing.
- Restored a persistent node-card `Copy connect command` path by storing revealable raw node tokens server-side for explicit on-demand copy while keeping hash-based auth verification.
- Routed the left sidebar pages through TanStack Router so `Home`, `Bros`, `Nodes`, and `Settings` keep their URL and survive refresh/direct open while sharing one live shell state.
- Changed browser voice mode to attach to the existing shell Synapse session instead of swapping to a connector-created voice session, and made the Agora connector default its channel name to that `session_id` with a generated unique fallback only when no session id is supplied.
- Added browser URL session resume through `?sid=...`, so the frontend now reopens an existing shell session when possible, rewrites `sid` to the active session id, and falls back to a fresh session with a warning when resume fails.
- Moved the `Interaction memory` pane off browser-local Agora transcript state so it now hydrates from Synapse durable conversation history on open and then continues from local user sends plus Synapse assistant stream events.
- Folded connector configuration into `newbro setup`, removed host-side detached executor prompts from that flow, and treated detached execution as an always-on control-plane capability while executor nodes remain the place where enabled executor families are declared.
- Added a first-class Synapse `user_message_appended` stream event and moved the `Interaction memory` pane fully onto Synapse user/assistant stream events after bootstrap, removing local user echo from the frontend.
- Changed `synapse service install` to restart `newbro.service` after installing and enabling the unit, so service-hosted deployments pick up the latest checkout immediately.
- Renamed the public package and CLI surface to `newbro-cli` / `newbro`, moved user config and workspace storage to `~/.newbro` with one-time migration from `~/.synapse`, and updated executor connect commands plus the systemd unit name to `newbro.service`.
- Removed the stale repo-root `newbro.py` launcher, kept `./newbro` as the only root bootstrap launcher, and made `newbro service install` fail fast when the installed `newbro` console script is missing or not executable.

- Adopted `newbro v0` as a draft-to-execute workflow: ASR turns update a mutable Draft, Send creates an immutable Task contract, and changing direction requires stopping and starting a new Draft.
- Changed Bro Detail ASR to use connector-managed STT sessions with fast RTC prepare, unique Agora-safe channels per page start, press-to-talk microphone control, explicit leave stop, and heartbeat timeout cleanup after more than 60 seconds without heartbeat.
- Changed Bro Detail STT defaults to recognize Chinese via `languages: ["zh-CN"]`, explicitly subscribe the STT bot to the browser RTC UID, and parse official JSON transcript wrappers.
- Changed Bro Detail STT defaults to recognize Chinese and English via `languages: ["zh-CN", "en-US"]`.
- Corrected Bro Detail STT join payload to use distinct publisher/subscriber bot UIDs, matching the Agora REST STT contract.
- Changed Bro Detail Draft Brain updates to submit the cumulative original-language ASR transcript, and made the deterministic draft display language follow Chinese ASR input with Chinese labels/defaults.
- Changed Bro Detail ASR handling so Agora protobuf `words[].isFinal` only stabilizes the current candidate; Draft Brain submission now commits the latest candidate once on mic release or short ASR silence.
- Changed Bro Detail ASR accumulation to follow Agora RTT-style subtitle segments: update the latest non-final segment by UID, keep final segments, and use STT timing metadata to reject stale revisions and sort late arrivals.
- Changed Bro Detail live ASR accumulation to merge Agora rolling-window candidates by suffix/prefix overlap, so shorter same-window regressions do not erase prior text and overlapping later windows only append new suffix text.
- Changed Bro Detail live ASR accumulation to a strict time-structured model: `payload.time` identifies the sentence segment, `text_ts` orders text parts inside that segment, and untimed payloads are ignored.
- Changed Bro Detail strict ASR accumulation so each `payload.time` sentence segment keeps only its latest `text_ts` candidate before sentence segments are joined by start time.
- Aligned Bro Detail STT parsing with Shengwang's current protobuf transcript contract, using `original_transcript` for translated payloads, treating `isFinal` as stable text rather than voice-turn completion, accepting provisional untimed candidates with `textTs`, and defaulting STT recognition to `["zh-CN"]`.
- Changed draft Send so runtime Bro assignment is tracked through persona metadata and `Persona.current_task_id`, while executor routing continues to use the runtime executor type.
- Added per-Bro-detail generation ids so draft tasks from the same Bro and executor binding reuse one execution session, while rebinding the Bro rotates the generation and hides old-generation tasks from Bro Detail recent tasks.
- Changed Draft Brain rewriting to use the LLM-backed Draft Cleaner prompt and fail when no LLM draft rewriter is configured, removing deterministic draft generation from the active runtime path.
- Changed Draft Cleaner output to plain sendable task text, with websocket `submit_asr_turn` streaming transient `draft_output_*` events while durable snapshots keep the existing `DraftSession` shape.
- Simplified the Draft protocol model to `text` and update summary; Send maps `Draft.text` into the immutable Task contract.

## 2026-04-30

- Changed the Codex executor adapter to normalize `agentMessage` commentary deltas into progress events so `ExecutionRun.latest_progress_message` updates during a run rather than only after completed assistant items.
- Removed the global Communication Persona prompt/config surface; worker Bro behavior is now configured through each persona's own `base_prompt`, and session snapshots no longer expose `communication_persona_prompt`.
- Renamed the active Python package namespace and source tree from `synapse` / `src/synapse` to `newbro` / `src/newbro`; `import synapse` is no longer supported, while existing `SYNAPSE_*` environment variables remain unchanged.

## 2026-05-22

- Added the v1 quiet runtime path where typed voice/text messages stage structured drafts, dispatch plans, deterministic gate outcomes, and short `RuntimeDecision` responses before creating immutable tasks.
- Added normalized agent-event storage with delivery policy so low-importance progress stays silent while blocked/completed/urgent events can produce short spoken responses.
- Changed the Agora ConvoAI bridge to submit turns through typed `stt_final` runtime messages and return the runtime decision text instead of always saying "Draft updated."
- Scoped browser ConvoAI Start to Bro detail pages, bound live ConvoAI turns to the current Bro voice target, and added bridge-side suppression for repeated cumulative ASR expansions.

## 2026-05-23

- Changed Agora ConvoAI ingestion to use typed `AgoraVoiceEvent` runtime events, with `/chat/completions` only translating explicit compatibility metadata and `RuntimeDecision.should_speak` as the sole TTS gate.
- Replaced the quiet-runtime semantic transcript classifier with a Communication Brain interaction-classifier boundary; model-backed classification is wired when an OpenAI-compatible provider is configured, while unconfigured final turns fail closed to uncertain clarification.
- Kept browser ConvoAI toolkit transcripts display-only because live toolkit finals can be growing fragments, while the connector coalesces repeated no-metadata custom LLM callbacks into one stable `stt.final` without text heuristics.
- Added live ConvoAI draft revisioning: `stt.partial` can run the interaction classifier on the configured cadence, voice draft updates refine one active draft silently, and Send validates the current draft revision before dispatch.
- Changed matching `stt.final` checkpoints to reuse the latest live draft revision, recording final boundary state without re-running classification or draft rewriting.
- Changed the live interaction-classifier contract so concrete task-shaped partial context can become draft-worthy before the final request phrase, without runtime keyword rules.
- Changed final voice draft decisions to speak one confirmation prompt per active Draft session when the dispatch gate asks for confirmation, while keeping partial and later revision updates silent.
- Kept dispatch-gate mode/risk reasons internal for send confirmation wording, so Codex-routed voice drafts use the normal send prompt instead of separate code-modification warning language.
- Tightened the model-backed interaction-classifier contract so active-draft short acceptances classify as confirmation, and ordinary research/planning/travel-help requests stay read-only/proposal unless side effects are explicit.
- Made confirmation with no active Draft a silent no-op and required successful voice sends to publish a cleared Draft snapshot.
- Clarified that active-draft utterances changing destination, date, budget, target, recipient, constraints, requirements, or deliverable content classify as Draft corrections rather than confirmations.
- Allowed a meaningful active-Draft correction to reopen one send-confirmation prompt for the corrected revision, while keeping duplicate finals and non-correction refinements silent.
