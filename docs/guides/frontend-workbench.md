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
- Bro detail page: design-style activity rail plus main pane, preserving the
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
  `Copy connect command` action on ordinary node cards
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
- Bro Detail draft input uses a separate connector-managed Agora STT path: the
  page first prepares a fresh Agora-safe channel and browser RTC token, then
  starts the ASR bot after the browser joins RTC with the microphone disabled
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
