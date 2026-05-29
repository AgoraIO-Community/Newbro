# Draft-to-Execute Protocol

`newbro v1` uses a quiet, voice/ASR-driven draft-to-execute workflow.
Bro Detail push-to-talk is the exception: typed input starts a direct Codex task
when the selected Bro is idle, or sends a typed executor-node text instruction
to the selected Bro's active executor session when Codex is already running. The
composer mic sends raw audio to the selected Bro's executor node. The executor
node transcribes the recording with local Whisper. If the selected Bro is idle,
Newbro creates the same kind of direct Codex task that typed PTT creates; if
Codex is already running, Newbro queues the transcript as direct Codex work in
the selected thread instead of routing through Communication Brain.
Neither path prepares a Draft, requires a separate Send confirmation, or creates
Communication Brain notification candidates for executor output.

The stable contract is:

```text
User utterance / ASR turn = append-only evidence
Draft = current mutable structured intent
Draft Revision = latest pre-send checkpoint for that mutable intent
Dispatch Plan = staged execution packet preview
Dispatch Gate = deterministic safety decision
Task = immutable execution contract after Send
```

## ASR Turn

An `AsrTurn` is one completed voice turn. It is evidence for Draft Brain and is
not executed directly.

Fields:

- `id`
- `raw_text`
- `normalized_text`
- `confidence`
- `started_at`
- `ended_at`

## Bro Detail Push-To-Talk Audio

Bro Detail composer push-to-talk audio is not an ASR or draft path. The browser
records only while the mic control is actively pressed, converts the local
recording to mono PCM, and uploads one raw audio instruction with explicit
thread intent. Existing-thread audio sends `target_thread_id`; first-send
audio in a pending new thread sends `create_new_thread=true`. The browser and
gateway clients do not run STT.

The mic is enabled only when all of these facts are true:

- the selected Bro is runtime-backed
- the Bro is bound to a connected executor node
- that node has a connected Codex executor
- the connected node advertises audio-instruction support, normally meaning
  local Whisper plus text follow-up is available

If any condition is false, recording is blocked before microphone capture starts.

The upload endpoint accepts raw PCM only and validates owner auth, target Bro,
connected Codex node, MIME type, duration, sample rate/channel metadata, size,
and exactly one thread intent: `target_thread_id` or `create_new_thread=true`.
The current limits are 60 seconds and 25 MB. Accepted audio is encoded as
JSON-safe PCM content inside the typed executor-node command; the detached node
does not read a backend-local audio path. If a matching active Codex run exists
for the resolved thread, Newbro dispatches it over the typed executor-node
protocol as `dispatch_audio_instruction` with an `ExecutorAudioInstruction`
payload. If no active run exists for that resolved thread, Newbro sends
`transcribe_audio_instruction`, receives a Whisper transcript from the executor
node, and creates a queued direct Codex task from that transcript.

Executor nodes advertise `supports_audio_instruction` only when they can accept
raw audio and produce a usable executor instruction. In the default path, the
node decodes the command's audio content and transcribes it with local Whisper.
Active-run audio returns a Whisper progress event that Newbro converts into a
queued direct Codex task for the selected thread; idle audio returns a direct
transcription response and Newbro starts that queued task immediately. This path
does not require Codex realtime audio or API-key realtime auth. Newbro does not
call Agora
prepare/activate, RTC, RTM, ConvoAI, Agora STT, Draft ASR, or Draft Send for
this composer mic path.

Executor-node Whisper transcription resamples browser PCM to Whisper's expected
16 kHz input rate, uses VAD/no-speech filtering, and does not condition a new
voice note on prior transcript text. If the recording is too short or Whisper
reports no clear speech, Newbro fails the voice note instead of creating a
direct Codex task from a likely hallucinated transcript.

Direct typed/PTT task `goal` and `latest_instruction` store only user-authored
input or executor-node transcripts. Persona/base-prompt text is executor
guidance and must not be persisted into user-visible task instruction fields or
rendered as a user message in Bro Detail.
When Codex or ACPX executes a direct Bro Detail typed/PTT task, the executor
turn input is the raw user text/transcript itself; Newbro must not wrap it in
`Task:`, `Goal:`, persona guidance, or any other prompt prefix.

Clients render the voice-note bubble before transcription completes. When the
executor node reports successful Whisper progress metadata, clients attach the
transcript under that same audio bubble rather than creating a separate user
chat turn. The executor node defaults to automatic language detection, and
foreground executor runs may override Whisper language and model with inline
arguments.

## Bro Detail ASR Lifecycle

Bro Detail uses a dedicated Agora STT bot for draft shaping. The connector owns
the STT bot lifecycle; the browser owns RTC join, local microphone tracks, and
press-to-talk interaction.

Entering Bro Detail follows this state machine:

```text
Enter Bro Detail
  -> prepare unique Agora-safe channel + browser RTC token
  -> browser joins RTC with mic disabled
  -> ASR bot starting
  -> ASR bot ready + mic off
```

Microphone interaction is press-to-talk:

```text
ASR bot ready + mic off
  -> press mic
mic enabled locally
  -> release mic
mic disabled locally
  -> final ASR segment may trigger Draft updating
  -> ASR bot ready + mic off
```

Each prepare call creates a fresh Agora `channel_name` instead of reusing the
Newbro session id. The channel is ASCII-safe, bounded to the Agora channel name
limits, and returned by the connector so the browser RTC join and STT bot join
use the same channel.

STT recognition defaults to one source language via Agora
`languages: ["zh-CN"]`, while explicit connector config can override the
language list. This follows Agora's quality and cost guidance to avoid
multi-language recognition unless the workflow needs it. The STT bot also
subscribes explicitly to the browser RTC UID so it transcribes the user's audio
source rather than relying on implicit channel subscription behavior. The STT
publisher and subscriber bot UIDs are distinct, matching the Agora REST STT join
contract.

The browser heartbeats active STT sessions every 15 seconds. Explicit Bro Detail
leave stops the STT bot immediately. If the browser disappears without leave,
the connector stops the STT bot after more than 60 seconds without heartbeat.

Bro Detail accumulates ASR as strict time-structured original-language text.
For official Agora protobuf payloads, the browser uses `original_transcript`
for translation messages when present and otherwise uses top-level `words`.
Official JSON aliases are normalized, including `offset` as the sentence start
time and `duration` as milliseconds. `text_ts` / `textTs` is treated as the
recency timestamp for a sentence's candidate text. Timed candidates are grouped
by UID and sentence start time; untimed candidates with `textTs` are held as the
current provisional sentence until timed metadata arrives. Within one sentence
segment, only the candidate with the latest `textTs` is retained; sentence
segments are sorted by `time` and then joined. For Agora STT payloads,
`words[].isFinal` and JSON wrapper `isFinal` mean the current candidate is
stable, not that the semantic voice turn ended. Draft updates receive the
cumulative original-language transcript on mic release, about 1.2 seconds of
ASR silence, or a legacy explicit `end_of_segment === true` signal. The browser
does not merge translated transcript text into this original transcript stream.

## Draft Session

A `DraftSession` is the mutable pre-send workspace for one potential task.
The runtime keeps one active draft session per Newbro session.

Fields:

- `id`
- `assigned_bro_id`
- `asr_turns`
- `current_draft`
- `current_dispatch_plan`
- `runtime_state`
- `snapshots`
- `status`
- `current_revision_id`
- `current_revision_number`
- `live_classification`
- `live_source_boundary`
- `live_transcript_timestamp_ms`
- `created_at`
- `updated_at`

## Draft

A `Draft` is the latest clean task intent shown to the user before Send.

Fields:

- `text`
- `last_update_summary`
- `task_spec`
- `missing_context`
- `revision_id`
- `revision_number`
- `updated_at`

`task_spec` is the structured grounding used for dispatch. It includes:

- `title`
- `goal`
- `target_agent`
- `mode`: `read_only_first`, `proposal_only`, `modify_allowed`, or `submit_allowed`
- `expected_output`
- `constraints`
- `success_criteria`
- `stop_conditions`
- `context`
- `input_language`
- `output_language`
- `raw_transcript`
- `normalized_task_language`
- `code_switched`

Draft Brain rewrites the Draft after each durable ASR turn or live transcript
checkpoint through the LLM-backed Draft Cleaner. The cleaner receives ordered ASR
turn evidence, the latest live or durable turn, the assigned Bro id, and the
previous draft. It emits only plain clean sendable task text, not JSON or labeled
sections. The runtime stores that text directly in `Draft.text`.

Live ConvoAI updates do not append one durable `AsrTurn` per partial fragment.
The runtime classifies the latest transcript snapshot at the configured cadence,
defaulting to about 1 second, and `delegation` or `draft_correction`
classifications refine the same active Draft session. Each refinement creates a
new `revision_id` / `revision_number` and snapshot. Final or coalesced callback
events can stabilize the live Draft when newer, but they are not required before
the UI can show the corrected Draft. When a final callback has the same
normalized transcript as the latest published live Draft, the runtime records a
final checkpoint for the existing revision instead of running the classifier and
Draft Cleaner again.

For live partials, the classifier should not wait for an explicit final request
phrase when the utterance already contains enough concrete task material to form
a useful draft. Pure greeting, preference, or background context remains
communication.

The Draft must keep only the current final execution intent, not the whole
revision history. Typed runtime message ingestion may use deterministic rewriting
for the quiet v1 path, while the legacy Draft Cleaner path still fails when no
LLM draft rewriter is configured.

## Dispatch Plan And Gate

Draft updates stage a `DispatchPlan` before execution. The plan records:

- `plan_id`
- `session_id`
- `draft_session_id`
- `draft_revision_id`
- `draft_revision_number`
- `intent`
- `target_agent`
- `task_title`
- `task_goal`
- `required_context`
- `missing_context`
- `mode`
- `risk_level`
- `confidence`
- `requires_user_confirmation`
- `user_confirmed`
- `output_language`
- `task_spec`

The deterministic dispatch gate returns one of:

- `ask_clarification`
- `ask_confirmation`
- `dispatch`
- `reject`

The gate blocks low-confidence drafts, missing context, unavailable target
agents, unsafe modes, unconfirmed medium/high-risk work, and side-effecting
plans. Models may propose task specs, but the gate decides whether execution can
start.

## Send Boundary

`Send` confirms the staged dispatch plan and freezes the current Draft revision
into a queued `Task`. The request may carry `draft_revision_id`; when present it
must match the active `DraftSession.current_revision_id`. If a newer live draft
revision exists, the stale Send is rejected before dispatch and no older draft is
converted into a task.

When `assigned_bro_id` matches a runtime `Persona`, Send assigns the created
task to that Bro by setting the task's persona metadata and marking the persona
`busy` with `current_task_id`. The task still uses the runtime executor type as
its executor; the Bro id is not treated as an executor id. If the Bro is bound
to an executor node, the node binding is copied into task metadata so execution
can wait on or dispatch to that node.

Each runtime Bro carries a `bro_detail_session_id` generation. Send copies that
generation into task metadata and uses it as the task's executor-session
continuity key. Draft tasks from the same Bro detail generation reuse one
executor session when the executor family and bound node also match. Rebinding
the Bro to a different executor node rotates the generation, so future tasks no
longer reuse the old executor session and the Bro detail UI no longer shows the
old generation in Recent tasks.

For v0, draft-created tasks store the draft contract in `Task.metadata`:

- `immutable: true`
- `source_kind: draft_session`
- `draft_session_id`
- `draft_snapshot_id`
- `draft_revision_id`
- `draft_revision_number`
- `asr_turn_ids`
- `assigned_bro_id`
- `draft_text`
- `task_spec`
- `dispatch_plan`
- `mode`
- `expected_output`
- `constraints`
- `success_criteria`
- `stop_conditions`
- `persona_id`, `persona_name`, `bro_detail_session_id`, and
  `executor_node_id` when Send targets a configured runtime Bro

After Send, later voice input creates or updates a separate draft session. It
must not mutate the sent task contract.

## Stop Boundary

`Stop Task` maps to the existing `cancel_task` command. The product labels
this terminal state as `Stopped`, while backend compatibility keeps the existing
`cancelled` task status.

## Runtime Decision

Typed `POST /api/sessions/{session_id}/messages` requests with `type` set to
`text`, `stt_partial`, or `stt_final` return a `RuntimeDecision`:

- `should_speak`
- `response_text`
- `interaction_type`
- `session_state`
- `ui_updates`
- `state_updates`
- `async_actions`
- `draft_session_id`
- `draft_revision_id`
- `dispatch_plan_id`
- `task_id`

Partial transcripts update UI state silently and, when the classifier cadence is
due, may also update the active live Draft revision. Delegation and correction
updates from partial voice stay silent. A final voice turn speaks one short
send-confirmation prompt when the dispatch gate is `ask_confirmation`, once when
the Draft first becomes ready and again only when a meaningful
`draft_correction` creates a new revision. Duplicate finals and non-correction
refinements continue to update the UI silently instead of repeating "draft
ready" prompts. Matching final checkpoints reuse the live revision without
repeating the prompt. The gate still records mode/risk reasons such as
unsafe mode or medium/high risk internally, but the user-facing send prompt stays
the same because downstream executors such as Codex own their own edit and
permission checkpoints. Clarification, permission, status, urgent, blocked, and
completed decisions may also speak. Confirmation turns dispatch only after the
gate passes. Confirmation turns with no active Draft are silent no-ops. A
successful send clears the active Draft before publishing the next session
snapshot. Status and stop turns resolve against the current blackboard task state.

Final free-form turns are interpreted through the Communication Brain
interaction-classifier boundary. The classifier returns structured fields such
as `interaction_type`, `confidence`, `requires_user_decision`, `importance`, and
`reason`. When a Draft exists, short final acceptance turns should classify as
`confirmation` unless they add correction or new task content. Utterances that
change destination, date, budget, target, recipient, constraints, requirements,
or deliverable content are `draft_correction`, not `confirmation`. Ordinary
research, planning, search, comparison, travel-help, review, and proposal turns
should not request `modify_allowed` unless the user explicitly asks for file
edits, external sends/bookings/purchases, account updates, or other side
effects. The runtime speech policy consumes classifier fields plus dispatch-gate
and blackboard state; it does not inspect transcript words to decide whether a
turn should speak. If no model-backed classifier is configured, the runtime
returns a safe `uncertain` clarification decision instead of falling back to
semantic runtime rules.

## Agora Voice Events

Agora Conversational AI voice input enters the runtime as typed voice events on
`POST /api/sessions/{session_id}/agora-events`. The event model is:

- `event_id`
- `session_id`
- `type`
- `text`
- `language`
- `timestamp_ms`
- `target_persona_id`
- `metadata`

Supported event types are:

- `stt.partial`
- `stt.final`
- `user.speech_started`
- `user.speech_ended`
- `assistant.speech_started`
- `assistant.speech_ended`
- `interaction.interrupted`
- `session.started`
- `session.ended`

`stt.partial` maps to the live transcript path. On the configured classifier
cadence, defaulting to about 1 second, it can classify the latest transcript
snapshot and refine the active Draft revision. `stt.final` stabilizes or
checkpoints that live state when newer; it is not the sole event allowed to
update the Draft. Whether any event speaks is determined by the returned
`RuntimeDecision.should_speak`. Speech lifecycle, interruption, and session
lifecycle events are silent UI/runtime state events unless later runtime policy
explicitly produces a spoken decision. The runtime does not infer finality,
quietness, meaning, or Bro routing from transcript text.

## Agent Events

Execution adapters and test harnesses can ingest normalized agent events through
`POST /api/tasks/{task_id}/events`.

Agent events store:

- `event_id`
- `task_id`
- `agent_id`
- `type`
- `message`
- `importance`: `low`, `medium`, `high`, or `urgent`
- `delivery`: `silent`, `silent_ui`, `badge`, `short_voice`, or
  `voice_interrupt`
- `artifact_id`
- `created_at`

Low-importance progress defaults to silent UI. Blocked, completed, urgent, and
short-voice events can produce short spoken responses through `RuntimeDecision`.
