# Design Update Port — Spec

**Date:** 2026-05-30
**Source:** `feat: design update` (commit `0a89c0f`) — the mockup folder under `design/`
**Target:** the production React UI under `src/newbro/ui/src/` and the runtime protocol where the reasoning stream needs it

## 1. Goal

Port the design update from the `design/` mockup folder to the production app, keeping brain boundaries intact. Most of the work is UI-only (copy, CSS tokens, gradient swaps, color shift, onboarding restructure, composer redesign). One slice is a deliberate protocol extension: a per-turn reasoning stream that replaces the current task-progress bar inside the working bubble.

## 2. Scope

### In scope

- Token additions and `--nb-ink-muted` darkening in `styles/app.css`.
- Color shift: bro chat bubbles and plan-mode UI move from coral to blue (`--nb-info-*`). User bubbles, CTAs, the mic button, and the active Plan-on chip keep coral (now via the new gradients).
- UI copy rename ("node" / "machine" / "executor" → "computer"; "Tap to send" → "Push to talk"; "Always on" → "Hands-free"; surrounding hint and placeholder copy).
- Onboarding sheet/modal restructure: STEP 1/2/3 framing, two stacked install command boxes, Hermes shown as disabled "Coming soon".
- Desktop composer bar redesign: in-bar Plan chip, mode-toggle icons + "Talk mode" eyebrow, press-and-hold PTT mic with inline live waveform and timer.
- Per-turn reasoning stream — protocol extension on `BroTimelineMessage`, new session-stream event lineage, new streaming reasoning bubble (desktop + mobile), collapsed "Reasoned ✓" pill for settled turns.
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
- `src/newbro/ui/src/types.ts` — extend `BroTimelineMessage` with `reasoning_steps`.
- `src/newbro/ui/src/__tests__/App.test.tsx` — update any asserted strings affected by the copy rename.
- **Backend** (paths to discover during planning, owned by Communication Brain): assistant message model gains `reasoning_steps`; session-stream emits `assistant_reasoning_step_appended` / `assistant_reasoning_step_completed`; `docs/protocol/session-stream.md` updated to document the new events.
- `docs/memories.md` appended once the protocol extension lands.

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

This is the only piece that crosses into runtime/protocol.

### 8.1 Protocol — `BroTimelineMessage` extension

Extend the assistant-side message on a turn:

```ts
export interface ReasoningStep {
  id: string;
  label: string;
  status: "active" | "done";
  started_at: string;        // ISO 8601
  completed_at: string | null;
}

export interface BroTimelineMessage {
  // existing fields…
  reasoning_steps: ReasoningStep[] | null;   // null for user role; null or [] for assistant turns that emitted none
}
```

Reasoning lives on the **turn's assistant message**, not on the task. Rationale: reasoning is the inner monologue of one round-trip; tasks span multiple turns and can be re-bound. The home-card progress already has a distinct concern (long-lived task state).

The backend persists the final `reasoning_steps` alongside the assistant message in conversation history, so a settled turn rendered from history can show the collapsed "Reasoned ✓" pill.

### 8.2 Stream events (session websocket)

Add two new server events to the lineage described in `docs/protocol/session-stream.md`, both correlated by `request_id` (and carry `turn_id` for fan-out):

- `assistant_reasoning_step_appended` — payload `{ request_id, turn_id, step: ReasoningStep }`. Emitted when a new reasoning line begins (status `active`) and again on subsequent text/label refinements within the same step id.
- `assistant_reasoning_step_completed` — payload `{ request_id, turn_id, step_id, completed_at }`. Emitted when a step settles (status → `done`).

Stream rules mirror existing assistant deltas:

- Deltas are transient. UI maintains the in-flight `reasoning_steps` list keyed by turn.
- The durable copy lands with the assistant message in conversation history once the turn closes (carried inside the next `snapshot` projection or the conversation projection per existing rules).
- Communication-model internal tool calls remain internal. Reasoning steps are user-visible narration only.

### 8.3 Adapter & view model

In `components/newbro/adapters.ts`:

- Map `assistant.reasoning_steps` to a per-turn `reasoningSteps` array on the turn view model.
- Derive a per-bro `latestReasoningStep: string | null` from the currently-active turn (the assistant message on the bro's latest in-flight turn). Used by the home bro card.

### 8.4 UI — live reasoning bubble

Render when the bro's current turn is in flight (assistant message exists, status `pending` or `running`, no `text` yet):

- Desktop: `.dt-bubble-bro.dt-bubble-reason` carrying `.dt-reason-kicker` ("{broName} is reasoning"), animated `.dt-reason-orb`, and `.dt-reason-steps` rolling window — show the **latest 3** steps; older steps fade to 0.55 / 0.26 opacity; newest is `.dt-reason-step-active`.
- Mobile: same structure with `.thr-reason*` classes; ships the new `ThrReasoned` collapsed component for settled turns.

### 8.5 UI — settled "Reasoned ✓" pill

Render when the assistant turn has a final `text`:

- Above the answer bubble, render a tucked-in pill (`.dt-reason-collapsed` / `.thr-reasoned`) with a check glyph + "Reasoned" label + chevron.
- Click toggles expansion. Expanded view shows the full `reasoning_steps` list inline (static `.dt-reason-steps-static` / `.thr-reason-steps-static`).
- Pill is hidden if `reasoning_steps` is empty / null.

### 8.6 UI — remove the progress bar

- The status-card progress UI at `ArtboardShell.tsx:504-550` (`thr-status*` / `dt-status*` family) is removed from the working-turn render path. It is replaced by the live reasoning bubble.
- The bro home-card progress at `ArtboardShell.tsx:1617-1642` swaps from `%` + bar to the latest reasoning step label (`bro.latestReasoningStep`), with a small animated 3-dot indicator while the turn is in flight. If `latestReasoningStep` is null, fall back to the existing `progressLabel`.

### 8.7 Tests

- Type-level test asserting `BroTimelineMessage.reasoning_steps` is optional/nullable and shaped correctly.
- Adapter test: a turn with `reasoning_steps` produces the expected `reasoningSteps` view model; an empty/null field yields `[]`/`null` and no pill renders.
- Visual test: rolling window keeps the last 3 active steps; older steps fade out; on completion, the collapsed pill renders.
- Stream-handling test: appending steps via `assistant_reasoning_step_appended` updates the in-flight turn; `assistant_reasoning_step_completed` flips status to `done`.

## 9. Implementation order (suggested phases)

1. **Tokens & color foundations** — `app.css` token additions, `--nb-ink-muted` darken, gradient swaps on existing flat-coral usages. Bro bubbles + plan-mode color shift.
2. **Copy rename** — UI strings across `ArtboardShell`, `NewbroShell`, `visual.tsx`, plus test asserts.
3. **Onboarding restructure** — `installOnly` builder; Step 1/2/3 labels; two command boxes; Hermes disabled card; updated status + footer copy.
4. **Composer redesign** — mode-toggle icons, in-bar Plan chip, press-and-hold mic, recording strip, hint copy.
5. **Reasoning stream — backend half** — `BroTimelineMessage.reasoning_steps`, two new session-stream events, `docs/protocol/session-stream.md` updated, focused tests.
6. **Reasoning stream — UI half** — adapter changes, live reasoning bubble, collapsed "Reasoned ✓" pill, bro-card rewire to `latestReasoningStep`.
7. **Memory note** — append a short factual line to `docs/memories.md` once §5 + §6 land.

## 10. Risks & open questions

- The press-and-hold PTT presentation needs to match the existing `useVoiceSession` start/stop semantics exactly. If those callbacks have setup latency, the inline waveform timer may need a small armed/recording distinction. Treat as an implementation detail to verify during the plan phase.
- Persisting `reasoning_steps` on conversation history requires storage decisions on the backend (likely already covered by the existing assistant message persistence path — to confirm during planning).
- The home bro card has multiple states beyond "working" (idle, offline, blocked). Only the working state changes; other states keep their existing labels. Confirm any edge cases when the bro has no active turn but has a recent task.
- "Hermes coming soon" should not be wired to any executor type. Make sure no codepath in `createExecutorNode` calls receives "hermes" as an `enabled_executors` value.
