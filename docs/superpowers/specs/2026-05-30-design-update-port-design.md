# Design Update Port — Spec

**Date:** 2026-05-30
**Source:** `feat: design update` (commit `0a89c0f`) — the mockup folder under `design/`
**Target:** the production React UI under `src/newbro/ui/src/` and the runtime protocol where the reasoning stream needs it

## 1. Goal

Port the design update from the `design/` mockup folder to the production app, keeping brain boundaries intact. Most of the work is UI-only (copy, CSS tokens, gradient swaps, color shift, onboarding restructure, composer redesign). One slice — the per-turn reasoning stream that replaces the current task-progress bar — is a thin **projection** change: the data already exists in the backend as `TaskExecutionDetailEntry` rows; the change is to surface a recent window of them on the session snapshot. No new event types, no Comm Brain change, no executor change.

## 2. Scope

### In scope

- Token additions and `--nb-ink-muted` darkening in `styles/app.css`.
- Color shift: bro chat bubbles and plan-mode UI move from coral to blue (`--nb-info-*`). User bubbles, CTAs, the mic button, and the active Plan-on chip keep coral (now via the new gradients).
- UI copy rename ("node" / "machine" / "executor" → "computer"; "Tap to send" → "Push to talk"; "Always on" → "Hands-free"; surrounding hint and placeholder copy).
- Onboarding sheet/modal restructure: STEP 1/2/3 framing, two stacked install command boxes, Hermes shown as disabled "Coming soon".
- Desktop composer bar redesign: in-bar Plan chip, mode-toggle icons + "Talk mode" eyebrow, press-and-hold PTT mic with inline live waveform and timer.
- Per-turn reasoning stream — surface the existing `TaskExecutionDetailEntry` window on the session snapshot's `ExecutionRun`, render a new streaming reasoning bubble (desktop + mobile), collapsed "Reasoned ✓" pill for settled turns (expanded via lazy `query_task_detail` read).
- Replace home bro-card progress (`%` + bar) with the latest reasoning step label + animated indicator.

### Out of scope

- Backend protocol terminology stays untouched: `executor_nodes`, `ExecutorNodeRecord`, `nodeId`, `--node-id`, `bind_node_token`, internal TS variable names. The rename is UI copy only.
- No second executor — "Hermes" is a visual placeholder card only, not a real executor.
- Voice/session state machine and audio capture (`useVoiceSession`) are not touched; the composer changes are presentation only.
- The task `progress: number` field stays on the protocol — it just stops driving any visible bar. Other consumers (analytics, future surfaces) remain unaffected.

## 3. Files touched (high level)

- `src/newbro/ui/src/styles/app.css` — token additions, `--nb-ink-muted` darken.
- `src/newbro/ui/src/styles/variants-desktop.css`, `variants-mobile-design.css`, `variants-onboarding.css` — per-component CSS for the color shift, reasoning bubble, composer, onboarding.
- `src/newbro/ui/src/ArtboardShell.tsx` — copy rename, onboarding sheet/modal restructure, composer redesign, reasoning bubble + collapsed pill, bro-card rewire.
- `src/newbro/ui/src/NewbroShell.tsx` — copy rename, "executor node" disabled-reason strings.
- `src/newbro/ui/src/components/newbro/visual.tsx` — sign-in copy.
- `src/newbro/ui/src/components/newbro/adapters.ts` — surface `reasoning_steps` on the bro/turn view model; derive bro-card "latest reasoning step" from active turn.
- `src/newbro/ui/src/lib/session-client.ts` — add `installOnly` builder; extend `ExecutorConnectCommands`.
- `src/newbro/ui/src/types.ts` — add `ExecutionDetailEntry`, add `recent_execution_details` to `ExecutionRun`.
- `src/newbro/ui/src/__tests__/App.test.tsx` — update any asserted strings affected by the copy rename.
- **Backend** (Execution Brain side): extend the session snapshot projection that already carries `ExecutionRun` so it includes `recent_execution_details` (last N `TaskExecutionDetailEntry` rows for the run). No executor change, no Comm Brain change, no new stream event types. Touch points are the runtime session-projection code path and its tests; exact module paths to confirm during planning (`src/newbro/runtime/session.py` is the likely site).
- `docs/memories.md` appended once the projection change lands.

## 4. Design tokens & color

### 4.1 Tokens (in `app.css`)

Add:

```
--nb-coral-grad:         linear-gradient(180deg, #ff8c5a 0%, #ff6a3d 100%);
--nb-coral-grad-btn:     linear-gradient(160deg, #ff8c5a 0%, #ff6a3d 60%, #e85528 100%);
--nb-coral-grad-btn-hover: linear-gradient(160deg, #ff7d4d 0%, #f05a2e 60%, #d4471f 100%);
--nb-live-grad-btn:      linear-gradient(160deg, #34d399 0%, #10b981 60%, #047857 100%);
--nb-info-grad-btn:      linear-gradient(160deg, #60a5fa 0%, #3b82f6 60%, #2563eb 100%);
```

Change:

```
--nb-ink-muted: #9ca3af  →  #7d8492   /* better contrast on white */
```

### 4.2 Where the gradients land

Swap flat `--nb-coral` to `--nb-coral-grad-btn` (and `-grad-btn-hover` on `:hover`) on:

- Desktop primary top-voice button, page primary action, send button, "in-bar" send.
- Round mic buttons (`dt-cmp-mic`, `dt-compose-mic-live`, mobile equivalents).
- The active Plan-on chip (`dt-cmp-planchip-on`) — becomes a solid coral gradient instead of tint+border.

User bubbles (both surfaces) use the flatter `--nb-coral-grad`.

### 4.3 Coral → blue shift

Recolor with `--nb-info-soft` / `--nb-info` / `--nb-info-ink` / `--nb-info-edge`:

- Bro chat bubbles: `.dt-bubble-bro`, `.thr-bubble-bro` background + border.
- Live "thinking" halo: `.thr-bubble-bro.thr-bubble-live` shadow goes blue.
- Plan proposal card: `.plan-prop` border, header background, glyph fill, eyebrow chip border/color.
- Plan options: `.plan-opt-on` background, border, shadow, radio dot.
- Plan approve button: `.plan-prop-approve` uses `--nb-info-grad-btn` with matching blue hover.
- Plan chip border accent on the composer while plan mode is on stays coral (signals an active user-initiated mode).

## 5. UI copy rename (UI-only)

Apply in `ArtboardShell.tsx`, `NewbroShell.tsx`, `components/newbro/visual.tsx`. Update `__tests__/App.test.tsx` asserts where they collide.

| Old | New |
| --- | --- |
| "node" / "executor node" / "machine" | "computer" |
| "Tap to send" | "Push to talk" |
| "Always on" | "Hands-free" |
| "Rotate token" | "Get a fresh link" |
| "How does this work?" | "Walk me through it" |
| "Listening for atlas…" | "Waiting to hear from your computer…" |
| "paused · node offline" | "paused · computer offline" |
| "Waiting for node…" | "Waiting for your computer…" |
| "Sending paused while the node is offline." | "Sending paused — reconnect your computer to resume" |
| "Name it, then connect a node." | "Set up your first bro" + intro paragraph (see §6) |
| "Connect a worker persona, bind it to a user-owned executor node…" | Rewritten per design (`FirstRunHome`) |

Protocol identifiers, TS variable names, CLI flags, and websocket field names stay as-is.

## 6. Onboarding sheet & modal

Source components: `CreateBroSheet` (mobile, in `ArtboardShell.tsx`) and `CreateBroModal` (desktop). Both adopt the same structural changes.

### 6.1 Header

- Eyebrow stays "NEW BRO".
- Title changes to **"Set up your first bro"**.
- New intro line below the title (`ob-sheet-intro`): "A bro works on a computer you keep on — your Mac, a spare laptop, anything. Three quick steps and it's ready."

### 6.2 Step framing

Replace field eyebrows:

- NAME → **STEP 1 · NAME IT**
- EXECUTOR → **STEP 2 · AGENT CLIENT**
- CONNECT A NODE → **STEP 3 · CONNECT A COMPUTER**

### 6.3 Agent client cards (Step 2)

- Codex card: description becomes **"OpenAI's coding agent"**. Stays selectable, stays the default.
- Hermes card: rendered as a **disabled "Coming soon"** state — visible for visual rhythm, not clickable, no backend call attempted. Description: "Open-source agent by Nous Research · Coming soon".
- A hint line below the grid: "Pick the one you already use — newbro runs your tasks through it. You can switch anytime."

### 6.4 Install commands (Step 3)

Replace the single `installConnect` block with **two stacked command boxes**, each with its own prose intro and copy button:

1. Box 1 — install:
   - Intro: "On the computer where atlas should work, paste this in a terminal to install newbro:"
   - Command: `curl -fsSL newbro.dev/install.sh | sh` (driven by a new `installOnly` builder in `session-client.ts`).
2. Box 2 — run:
   - Intro: "Then start it with your one-time key — we filled in the details for you:"
   - Command: the existing `runOnly` from `buildExecutorConnectCommands` (`newbro executor run --base-url … --node-id … --token …`).

`session-client.ts` changes:

- Add `installOnly: string` to `ExecutorConnectCommands`.
- Add `buildExecutorInstallOnlyCommand()` returning just `curl -fsSL ${NEWBRO_CLI_INSTALL_URL} | sh` (no trailing run args).
- `buildExecutorConnectCommands` now returns `{ installConnect, installOnly, runOnly }`. `installConnect` stays for any callsite that still wants the one-liner.

### 6.5 Status row & footer

- Live status line ("Listening for atlas") → **"Waiting to hear from your computer… This updates on its own once atlas connects. Nothing else on that computer changes."**
- Meta links: "Rotate token" → **"Get a fresh link"**; "How does this work?" → **"Walk me through it"**.
- Modal footer status: "Listening on relay.newbro.dev · token valid 9:46" → **"We'll detect your computer automatically · link valid 9:46"**.
- Disabled CTA: "Waiting for node…" → **"Waiting for your computer…"**.

### 6.6 Empty/first-run state

- `FirstRunHomeVariant` / `FirstRunHomeDesktop` hero copy updated to the new "A bro is a teammate that works on a computer you trust" framing.
- Sign-in subtitle (mobile + desktop) updated to the "lives on a computer you trust" line.
- "Add a bro" sub copy: "Name them, then connect a node" → **"Name it, then connect a computer"**.

## 7. Desktop composer redesign

Source: the production analog of `DTComposerBar` inside `ArtboardShell.tsx`.

### 7.1 Mode toggle

- Wrap the toggle in `.dt-cmp-modewrap` with a leading eyebrow label **"TALK MODE"**.
- Each option (`ptt`, `free`) gains a small SVG icon (mic / hands-free) inline with the label.
- Active option tints the icon: coral for `ptt`, green for `free`.

### 7.2 Plan chip

Moves from beside the toggle to **inside the composer bar** as the first child (`planChip`). Same shift+tab affordance, same on/off behavior, but the chip now visually leads the input.

### 7.3 PTT bar — press-and-hold mic

- Trailing button is press-and-hold (`onPointerDown` → start, `onPointerUp/Leave/Cancel` → stop). While recording, the input area swaps to an inline recording strip: red dot, "Listening…", live waveform (30 bars, sin-driven heights, staggered animation), `0:NN` timer, and a "release to send" hint.
- When `text.trim()` is non-empty and not recording, the trailing button swaps to a **send arrow** (`dt-cmp-action-send`). Recording is suppressed in that state.
- Hint text updates by state:
  - Recording → "Recording… release the mic to send"
  - Has text → "Press Enter to send"
  - Otherwise → "Hold Space to talk, or type your message"
  - Disabled → "Sending paused — reconnect your computer to resume"
  - Hands-free silent → "Mic's open — just speak; {broName} replies when you pause"
  - Hands-free engage → "Mic's open — {broName} may chime in as you go"

Audio capture wiring stays with `useVoiceSession`. The recording-strip state is local presentational state (`recording`, `recSecs`); it triggers `useVoiceSession`'s existing start/stop callbacks at the same lifecycle moments as today's mic button.

### 7.4 Mobile composer

Only label changes: "Tap to send" → "Push to talk"; "Always on" → "Hands-free"; "Always on · tap to talk" → "Hands-free · tap to talk". No structural changes.

## 8. Per-turn reasoning stream

The reasoning data **already exists** in the backend; the newbro layer needs no new emission or narration path. The change is purely a projection + UI surface.

### 8.1 Current state — what's already there

- The codex executor already emits `ExecutorEvent(event_type=PROGRESS, message=...)` at every meaningful step (4 emit sites in `executors/adapters/codex/executor.py`).
- `execution/run_manager.py` consumes each event and **already appends** a `TaskExecutionDetailEntry` (text + payload, anchored to `task_id` + `run_id`) for every progress / plan / waiting / blocked / completed / failed event — see `should_append_detail` (`run_manager.py:69-167`).
- `docs/protocol/task-execution-detail.md` already specifies: "per-task reads may be bounded to the most recent N entries while preserving append order." That is exactly the rolling window the reasoning UI needs.
- The PTT and text submission paths (`api/ws/stream.py` → `_handle_send_message` / `_handle_submit_asr_turn` → runtime → executor) are unchanged. The reasoning stream rides their existing output.

What's missing today is only that the UI's session snapshot projection surfaces `run.latest_progress_message` (a single string) and not the recent `TaskExecutionDetailEntry` window.

### 8.2 Backend change — snapshot projection only

Extend the runtime session snapshot projection (the one that already carries `ExecutionRun` to the UI) to include, per active run, a bounded recent window of its `TaskExecutionDetailEntry` rows.

Proposed shape on `ExecutionRun` (as projected to the UI; the durable model is already `TaskExecutionDetailEntry` and stays unchanged):

```ts
// in ui/src/types.ts, alongside ExecutionRun
export interface ExecutionDetailEntry {
  detail_id: string;
  event_type: string;          // PROGRESS | PLAN | WAITING_EXECUTOR | BLOCKED | COMPLETED | FAILED | CANCELLED
  text: string;                // already the normalized "detail line"
  created_at: string;
}

export interface ExecutionRun {
  // existing fields…
  recent_execution_details: ExecutionDetailEntry[];   // capped, append-ordered, newest last
}
```

Server-side: the projection reads from the existing store (`append_task_execution_detail` → backed by blackboard) and copies the **last N** entries (N = 8 is enough headroom for the 3-line rolling window with a small replay buffer). No new event types, no Comm Brain involvement, no new persistence model.

For history (settled turns), entries are already persistent via `TaskExecutionDetailEntry`. The collapsed "Reasoned ✓" pill expansion fetches the full per-task list lazily via the existing `query_task_detail` read API rather than packing all of it into the snapshot.

### 8.3 What does not change

- No new session-stream event type. The existing snapshot diff already pushes `ExecutionRun` updates; the new `recent_execution_details` field rides along.
- No change to Communication Brain. The Comm Brain prompt/policy/tools are untouched. This is consistent with AGENTS.md: "Keep transport thin" and "the newbro layer is very thin, this should not change."
- No change to `BroTimelineMessage`. Reasoning is sourced from the run linked to the turn's task (`turn.task.task_id` → run → `recent_execution_details`). No new field on the message model.
- No change to executor code. Codex already emits the events; new executors that emit PROGRESS will get reasoning UI for free.

### 8.4 Adapter & view model

In `components/newbro/adapters.ts`:

- Join `turn.task.task_id` → the matching `ExecutionRun` → `recent_execution_details` → expose a `reasoningSteps: ReasoningStep[]` array on the turn view model. The adapter maps each entry to `{ id: detail_id, label: text, status: "done" | "active" }` (the newest entry in an in-flight run is "active"; older are "done"; in a settled run all are "done").
- **Filter by `event_type`**: include only `PROGRESS` and `PLAN` entries. Terminal states (`BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`) and `WAITING_EXECUTOR` are excluded — those have dedicated UI (status pills, terminal bubbles, offline banners) and would clutter the reasoning rolling window.
- Derive a per-bro `latestReasoningStep: string | null` from the bro's active turn's run (latest filtered entry's `text`). Used by the home bro card.
- If `recent_execution_details` is missing or contains no `PROGRESS`/`PLAN` entries, `reasoningSteps` is `[]` — the live bubble simply doesn't render reasoning, and no "Reasoned ✓" pill appears on the settled turn.

### 8.4 UI — live reasoning bubble

Render when the bro's current turn is in flight (assistant message exists, status `pending` or `running`, no `text` yet):

- Desktop: `.dt-bubble-bro.dt-bubble-reason` carrying `.dt-reason-kicker` ("{broName} is reasoning"), animated `.dt-reason-orb`, and `.dt-reason-steps` rolling window — show the **latest 3** steps; older steps fade to 0.55 / 0.26 opacity; newest is `.dt-reason-step-active`.
- Mobile: same structure with `.thr-reason*` classes; ships the new `ThrReasoned` collapsed component for settled turns.

**Plan-mode interaction**: the reasoning bubble renders during plan generation just like during execution — codex emits the same `PROGRESS`/`PLAN` events in both phases. When the plan finalizes, the in-flight turn transitions to its plan-proposal state and the reasoning bubble is replaced by the **plan proposal card** in the same slot (the proposal card carries its own "Reasoned ✓" collapsed pill above it if the run produced any reasoning steps). No special suppression logic; the bubble's exit is driven by the turn moving from "no final output" to "plan proposal available".

### 8.5 UI — settled "Reasoned ✓" pill

Render when the assistant turn has a final `text`:

- Above the answer bubble, render a tucked-in pill (`.dt-reason-collapsed` / `.thr-reasoned`) with a check glyph + "Reasoned" label + chevron.
- Click toggles expansion. Expanded view shows the full `reasoning_steps` list inline (static `.dt-reason-steps-static` / `.thr-reason-steps-static`).
- Pill is hidden if `reasoning_steps` is empty / null.

### 8.6 UI — remove the progress bar

- The status-card progress UI at `ArtboardShell.tsx:504-550` (`thr-status*` / `dt-status*` family) is removed from the working-turn render path. It is replaced by the live reasoning bubble that renders `reasoningSteps` from the active run.
- The bro home-card progress at `ArtboardShell.tsx:1617-1642` swaps from `%` + bar to the latest reasoning step label (`bro.latestReasoningStep`), with a small animated 3-dot indicator while the turn is in flight. If `latestReasoningStep` is null, fall back to the existing `progressLabel`.

### 8.7 Tests

- Backend projection test: an `ExecutionRun` produced by the session snapshot carries the last N `TaskExecutionDetailEntry` rows in `recent_execution_details`, append-ordered, capped at N.
- Adapter test: a turn whose task has `recent_execution_details` populated produces the expected `reasoningSteps` view model (latest entry is `active` while the run is RUNNING; all `done` once the run terminates). An empty list yields `reasoningSteps = []` and no pill renders.
- Visual test: rolling window keeps the last 3 entries; older entries fade out; on terminal run state, the collapsed pill renders above the answer.
- No new stream-event handler test is needed — existing snapshot-diff plumbing is reused.

## 9. Implementation order (suggested phases)

1. **Tokens & color foundations** — `app.css` token additions, `--nb-ink-muted` darken, gradient swaps on existing flat-coral usages. Bro bubbles + plan-mode color shift.
2. **Copy rename** — UI strings across `ArtboardShell`, `NewbroShell`, `visual.tsx`, plus test asserts.
3. **Onboarding restructure** — `installOnly` builder; Step 1/2/3 labels; two command boxes; Hermes disabled card; updated status + footer copy.
4. **Composer redesign** — mode-toggle icons, in-bar Plan chip, press-and-hold mic, recording strip, hint copy.
5. **Reasoning stream — backend projection** — extend the session snapshot projection so each `ExecutionRun` carries `recent_execution_details` (last N `TaskExecutionDetailEntry` rows). Add the matching field to `ui/src/types.ts`. No new event types, no Comm Brain change.
6. **Reasoning stream — UI half** — adapter changes (`reasoningSteps`, `latestReasoningStep`), live reasoning bubble, collapsed "Reasoned ✓" pill driven by lazy `query_task_detail` read, bro-card rewire to `latestReasoningStep`.
7. **Memory note** — append a short factual line to `docs/memories.md` once §5 + §6 land.

## 10. Risks & open questions

- The press-and-hold PTT presentation needs to match the existing `useVoiceSession` start/stop semantics exactly. If those callbacks have setup latency, the inline waveform timer may need a small armed/recording distinction. Treat as an implementation detail to verify during the plan phase.
- Cap size for `recent_execution_details` — `N = 8` is the proposed starting point. Re-check during planning that this is small enough to keep snapshot diffs cheap but large enough to cover the 3-line rolling window with replay headroom on reconnect.
- Existing `TaskExecutionDetailEntry.event_type` is broad (PROGRESS / PLAN / WAITING_EXECUTOR / BLOCKED / COMPLETED / FAILED / CANCELLED). The reasoning UI primarily wants PROGRESS lines. Decide during planning whether the adapter filters by `event_type === "PROGRESS"` or shows everything (terminal states get their own UI elsewhere, so filtering is likely the right call).
- The home bro card has multiple states beyond "working" (idle, offline, blocked). Only the working state changes; other states keep their existing labels. Confirm any edge cases when the bro has no active turn but has a recent task.
- "Hermes coming soon" should not be wired to any executor type. Make sure no codepath in `createExecutorNode` calls receives "hermes" as an `enabled_executors` value.
