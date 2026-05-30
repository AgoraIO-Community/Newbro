# Frontend Workbench

The main frontend under `src/newbro/ui/` renders the active `Newbro` runtime
shell at `/`.

It keeps the protocol-first runtime behavior, but the active shell now follows
the checked-in design prototype under `design/`: a compact glass top header,
light gray workspace surface, bordered paper panels, coral primary actions,
green live state, mono operational labels, design-port Bro avatars, empty
onboarding cards, and mobile Walkie/detail variants.

## Current Structure

The current frontend stack is:

- React
- Vite 8
- TanStack Router
- Tailwind CSS v4
- `framer-motion` for shell motion
- Agora connector/browser voice integration for live transcript state

- desktop top header: `Home`, `Bros`, `Nodes`, `Settings`, account, logout, and
  runtime readiness
- home page: design workspace with top voice control, runtime Bro grid,
  runtime/node rail, and an explicit empty workspace card when no personas
  exist
- Bro detail page: design-style real thread rail plus main pane, preserving the
  Draft/STT/send/talk controls and disconnected-node warning behavior
- setup/connect state: design cards and first-run sheet for creating or
  revealing the current Bro's local node command before Bro Detail unlocks
- mobile route: `MobileWalkie` channel surface sourced from runtime Bro cards,
  with mobile-safe header/detail states and no horizontal page overflow
- management pages: Bro management on `Bros`, node enrollment on `Nodes`
- navigation pages are real routed paths, so refresh and direct open preserve the
  selected page instead of falling back to `Home`

## Data Sources

Current reads and live transport:

- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `WS /api/sessions/{session_id}/stream`
- `GET /api/sessions/{session_id}/personas`
- `GET /api/sessions/{session_id}/executor-nodes`
- `GET /api/connectors/agora-convoai/config`
- `POST /api/connectors/agora-convoai/sessions/prepare`
- `POST /api/connectors/agora-convoai/sessions/activate`
- `POST /api/connectors/agora-convoai/sessions/stop`

Current behavior:

- on load, the app resumes the shell session from `?sid=...` when present;
  otherwise it creates an idle shell session and fetches its snapshot
- once the shell has an active session, it writes that session id back to the
  URL as `sid` so the session can be reopened later from the same link
- if `sid` cannot be resumed, the app opens a fresh session, replaces the URL
  `sid`, and shows a non-blocking resume-failed warning
- the active session stream keeps `personas` and `executor_nodes` fresh while
  the shell stays open
- the `Home` route remains the workspace when runtime Bros exist; explicit Bro
  Detail navigation uses Bro cards or `/bros/:broId`
- if persona data is empty, the home view renders the design empty workspace
  instead of replacing runtime state with seeded active cards
- the empty workspace `Create your first bro` action opens a design-backed
  first-run sheet that creates a real executor node, shows the issued connect
  command, and waits to create the Bro persona until the node has connected
  successfully once
- Bro liveness is derived from `persona.executor_node_id` plus the matching
  executor node connection state
- the `Bros` page edits each worker Bro's base prompt, avatar, and node binding
- the `Nodes` page creates, edits, rotates, and deletes executor nodes and
  shows the token on create/rotate plus a persistent on-demand
  `Copy install + connect` action on ordinary node cards, with run-only
  `newbro executor run ...` still available for already-installed machines
- sidebar navigation preserves the current `sid` query parameter across
  `Home`, `Bros`, `Nodes`, and `Settings`
- `Interaction memory` hydrates from Newbro durable conversation history when
  the page/session opens, then continues from Newbro user-message and
  assistant stream events instead of relying on local user echo or
  browser-local Agora transcript turns
- pressing `Start` prepares a connector-backed voice session against the
  current shell `session_id`, so the voice binding attaches to the existing
  Newbro session instead of swapping the shell to a new one
- when the browser does not pass an explicit `channel_name`, the connector uses
  that current shell `session_id` as the Agora channel and falls back to a
  unique generated channel only if no Newbro session id is available
- pressing `Stop` tears down only the live voice session and retains the last
  transcript until the next live session replaces it
- Bro Detail push-to-talk typed input bypasses Communication Brain and the
  Draft card: submitting the composer starts a direct Codex task when the Bro is
  idle, or sends a typed executor-node text instruction to the selected Bro's
  active executor session when Codex is already running, instead of calling
  session messages, draft ASR, or draft Send endpoints. The composer must send
  explicit thread intent for both text and PTT audio: selected threads use
  `targetThreadId`, and an empty/pending new thread uses `createNewThread=true`
- Bro Detail typed input supports plan mode on desktop and mobile. When enabled,
  direct text sends `planMode=true`, renders the user bubble with a plan-mode
  tag in optimistic and canonical history, and expects Codex to propose before
  acting through native collaboration mode. Proposal choices render from
  `InteractionRequest(kind="plan_proposal").details.proposal`; clients must not
  infer options from free-form assistant text. Pending proposal cards render
  inline with their task turn when possible; if the active Bro Detail thread has
  a pending proposal that cannot be matched to a rendered turn yet, clients
  render it as a thread-level approval card using `details.target_thread_id` and
  `details.persona_id`.
- Bro Detail desktop left rail and mobile drawer render real Codex-backed
  `bro_threads` from the runtime snapshot, not task records. Selecting a thread
  calls the open-thread endpoint, writes `thread` into the URL, and direct
  text/PTT sends include that target so completed selected Codex threads resume
  through their stored execution-session resume handle. The frontend does not
  call Codex app-server subscription APIs directly: Newbro's open-thread
  endpoint asks the bound executor node to subscribe to selected-thread events in
  the background, and the close-thread endpoint releases that subscription when
  Bro Detail leaves the thread, starts a new pending thread, or unmounts. The
  snapshot can include Codex threads imported through the connected executor
  node's `thread/list` capability even when Newbro has not created task history
  for that native thread yet; opening one reuses the cached imported-thread
  projection instead of refreshing the global list, then loads native Codex
  history into canonical `bro_timeline_turns` for display without creating
  Newbro `Task`, `ExecutionRun`, or `TaskSummary` records. Bro Detail renders
  the selected thread from `SessionSnapshot.bro_timeline_turns` only, plus
  local optimistic text/audio placeholders that already use the same turn shape
  and are replaced by canonical backend turns via `client_request_id`. It no
  longer timestamp-merges local text turns, local audio turns, task records,
  conversation messages, and native executor messages. Both sides of
  direct/native turns render from the same object: each user instruction
  appears as the existing user bubble, and assistant/native/task output appears
  in the existing task output card. Native Codex response turns expose only the
  latest assistant/agent message for that executor turn; while a turn is
  running, newer assistant/agent messages replace the previous one in place.
  Audio transcripts render inside the audio user message instead of as a second
  text bubble. User bubbles, audio turns, and task output cards display
  timestamps from the originating timeline turn or message. The selected thread
  timeline is rendered oldest-to-newest and desktop/mobile panes scroll to the
  bottom when opening a thread or receiving new selected-thread content. Task
  output cards render the original markdown-like assistant/task summary
  structure instead of the flattened one-line preview used for compact records.
  Task output cards also render explicit `Goal` and `Plan` sections when the
  backend projection provides them. Plans come from documented Codex plan
  events/items or Newbro run metadata, not from Codex reasoning or inferred
  commentary.
  Pending `plan_proposal` requests render proposal cards with option selection,
  `Implement it`, and `Keep planning`; `Implement it` renders an optimistic
  user text turn with visible text `Implement it` and resolves the interaction
  request with `approve`, `client_request_id`, and `user_visible_text`.
  `Keep planning` resolves the request with `deny` but means refine the
  proposal, not cancel the task. Resolved
  `plan_proposal` requests are acknowledgements only; Bro Detail removes the
  proposal card after snapshot refresh and shows follow-up execution state
  through the task/run timeline or a new pending request.
  Desktop and mobile thread pickers render long thread lists in pages of 25 and
  expose an inline show-more control while auto-expanding enough to keep a
  URL-selected thread visible.
- `New thread` is a pending UI target and creates no Codex thread until the
  first direct send.
- Bro Detail push-to-talk mic input records local browser audio only while
  pressed, converts it to raw PCM, and uploads it to Newbro for dispatch to the
  selected Bro's executor node. Newbro carries the PCM content in the
  executor-node command payload instead of sending a backend-local file path;
  the node transcribes with local Whisper and Newbro creates a queued direct
  Codex task from that transcript in the selected Bro thread. Idle Bros start
  that direct task after transcription; active Bros queue the transcript behind
  the current turn.
- The composer shows the audio bubble immediately, then displays the Whisper
  transcript under that same bubble after executor-node transcription succeeds
- the mic is disabled until the selected Bro has a connected bound Codex node
  and that node advertises audio-instruction support
- The Bro Detail push-to-talk mic path must not prepare or activate Agora,
  join RTC/RTM, call ConvoAI/STT, create draft ASR turns, or require Send
  confirmation
- Bro Detail draft/free voice input uses a separate connector-managed Agora STT
  path: the page first prepares a fresh Agora-safe channel and browser RTC
  token, then starts the ASR bot after the browser joins RTC with the microphone
  disabled
- Bro Detail does not use the shell `session_id` as the Agora channel name;
  each page start receives a unique channel from the connector to avoid channel
  conflicts
- Bro Detail sends STT heartbeats every 15 seconds; explicit leave stops the ASR
  bot immediately, and missing heartbeats for more than 60 seconds stop it from
  the connector side

## Component Direction

The visual shell uses reusable pieces under `src/components/newbro/` plus
design CSS copied into `src/styles/` from the prototype:

- `BroAvatar`
- `BrosPanel`
- `BrosPage`
- `NodesPage`
- `BroCard`
- `BroPortrait`
- `BroProgress`
- `NewbroLogo`
- `WindowDots`
- `VoicePad`
- `DraftBrainPanel`
- `LiveTranscriptPanel`
- `RunnerBrainPanel`
- `useVoiceSession`

The visual language should stay close to the `design/` prototype:

- light gray app background with white bordered panels
- orange `#ff6a3d` as the main action color
- green live/listening state with restrained status cards
- compact Inter-like headings rather than poster-scale display type
- monospace operational labels via the design token font stack
- compact top navigation, Bro cards, setup cards, and mobile channel surfaces
- pill-shaped hold-to-talk control with animated listening bars

## Constraints

- Do not change backend or protocol contracts for cosmetic reasons.
- Keep the transport/runtime separation intact: the left-pane interaction
  memory comes from Newbro conversation state, while the voice connector owns
  RTC/RTM/session lifecycle and browser-local microphone/media behavior.
- Treat `src/newbro/ui/` as the only active frontend.
- Do not reintroduce the old chat/workbench root experience unless a later task
  explicitly broadens scope.
