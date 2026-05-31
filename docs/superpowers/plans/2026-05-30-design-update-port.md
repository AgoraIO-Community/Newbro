# Design Update Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the `feat: design update` mockups from `design/*` to the production React UI, including the supporting backend snapshot projection that surfaces existing `TaskExecutionDetailEntry` rows on the session snapshot so the new reasoning bubble can render.

**Architecture:** Most tasks are UI-only — CSS token additions and swaps, copy renames, onboarding restructure, composer redesign. One slice (Tasks 12–13) is a thin backend projection change: surface `recent_execution_details` on `SessionSnapshot` keyed by `task_id`, populated from the existing `Blackboard.list_recent_task_execution_details(...)` reader. No new websocket event types, no Communication Brain change, no executor change. The UI's reasoning bubble joins `turn.task.task_id → recent_execution_details[task_id]`, filters to PROGRESS + PLAN events, and renders a rolling 3-step window. Settled turns get a collapsed "Reasoned ✓" pill.

**Tech Stack:** TypeScript + React (Vite) for the UI; Pydantic models in `src/newbro/protocol/` and `src/newbro/runtime/` for the backend; vitest for UI tests; pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-05-30-design-update-port-design.md`

**Design source (read-only reference):** `design/tokens.css`, `design/variants-desktop.{css,jsx}`, `design/variants-mobile.{css,jsx}`, `design/variants-onboarding.{css,jsx}`, `design/app.jsx`. Every task references concrete line ranges in these files; the implementer should read those ranges before editing the production equivalents.

**Production targets (high level):**
- Tokens: `src/newbro/ui/src/styles/app.css`
- Variant CSS: `src/newbro/ui/src/styles/variants-desktop.css`, `variants-mobile-design.css`, `variants-onboarding.css`
- UI shells: `src/newbro/ui/src/ArtboardShell.tsx` (4000 lines), `NewbroShell.tsx`, `components/newbro/visual.tsx`
- Adapter / types: `src/newbro/ui/src/components/newbro/adapters.ts`, `src/newbro/ui/src/types.ts`, `src/newbro/ui/src/lib/session-client.ts`
- Backend snapshot: `src/newbro/runtime/models.py`, `src/newbro/runtime/session.py`
- UI tests: `src/newbro/ui/src/__tests__/App.test.tsx`
- Backend tests: `tests/unit/runtime/test_session_runtime.py`

**Run commands:**
- Backend tests: `.venv/bin/python -m pytest <path>`
- UI tests: `cd src/newbro/ui && npm test -- <pattern>`
- UI build/typecheck: `cd src/newbro/ui && npm run build` (runs `vite build && tsc --noEmit`)

---

## Task 1: Add design tokens to `app.css` and darken `--nb-ink-muted`

**Files:**
- Modify: `src/newbro/ui/src/styles/app.css:35-72`

**Reference:** `design/tokens.css:30-80` (the new token definitions).

- [ ] **Step 1: Read the target lines in `app.css`**

Run: `sed -n '30,80p' src/newbro/ui/src/styles/app.css`
Expected: see the existing `--nb-coral`, `--nb-ink-muted`, `--nb-info` token families with the production values.

- [ ] **Step 2: Add the new gradient tokens immediately after the existing `--nb-coral-shadow` line**

Insert these new tokens after `--nb-coral-shadow: rgba(255, 106, 61, 0.25);`:

```css
    /* Coral gradients — synced with the mobile design language.
       -grad      : flatter 2-stop for message bubbles / large surfaces
       -grad-btn  : richer 3-stop for circular/pill action buttons */
    --nb-coral-grad:           linear-gradient(180deg, #ff8c5a 0%, #ff6a3d 100%);
    --nb-coral-grad-btn:       linear-gradient(160deg, #ff8c5a 0%, #ff6a3d 60%, #e85528 100%);
    --nb-coral-grad-btn-hover: linear-gradient(160deg, #ff7d4d 0%, #f05a2e 60%, #d4471f 100%);
```

- [ ] **Step 3: Darken `--nb-ink-muted`**

Replace:
```css
    --nb-ink-muted: #9ca3af;
```
with:
```css
    --nb-ink-muted: #7d8492;     /* tertiary, metadata, hints — kept legible on white (~3.6:1) */
```

- [ ] **Step 4: Add the green button gradient near the live token block**

Find the existing `--nb-live-edge:` line and insert immediately after it:

```css
    /* Green button gradient — mobile listening/recording mic */
    --nb-live-grad-btn: linear-gradient(160deg, #34d399 0%, #10b981 60%, #047857 100%);
```

- [ ] **Step 5: Add the blue button gradient near the info token block**

Find the existing `--nb-info-edge:` line and insert immediately after it:

```css
    /* Blue button gradient — mirrors --nb-coral-grad-btn for plan-mode approve */
    --nb-info-grad-btn: linear-gradient(160deg, #60a5fa 0%, #3b82f6 60%, #2563eb 100%);
```

- [ ] **Step 6: Run UI build to confirm CSS still parses**

Run: `cd src/newbro/ui && npm run build`
Expected: build completes without CSS parse errors (TypeScript warnings unrelated to this task are fine).

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/styles/app.css
git commit -m "feat(ui): add gradient tokens and darken --nb-ink-muted"
```

---

## Task 2: Apply coral → blue color shift on bro bubbles and plan-mode UI

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (bro bubble + plan-prop rules)
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css` (bro bubble + plan-prop rules)

**Reference:** `design/variants-desktop.css` and `design/variants-mobile.css` — the diffs in commit `0a89c0f` show the exact line-by-line swaps. Concretely:
- `.dt-bubble-bro` background goes from `var(--nb-paper-sub)` to `var(--nb-info-soft)`; border from `var(--nb-line)` to `var(--nb-info-edge)`.
- `.thr-bubble-bro` background goes from `white` to `var(--nb-info-soft)`; border from `rgba(0,0,0,0.06)` to `var(--nb-info-edge)`.
- `.thr-bubble-bro.thr-bubble-live` box-shadow goes from coral-tinted to blue-tinted (`rgba(59,130,246,0.1)`).
- `.plan-prop` border → `var(--nb-info-edge)`.
- `.plan-prop-head` background → `var(--nb-info-soft)`; `.plan-prop-glyph` background → `var(--nb-info)`.
- `.plan-prop` `MODE` eyebrow chip: color → `var(--nb-info-ink)`; border → `var(--nb-info-edge)`.
- `.plan-opt-on` background → `var(--nb-info-soft)`, border → `var(--nb-info)`, shadow → `rgba(59,130,246,0.18)`.
- `.plan-opt-on .plan-opt-radio` border → `var(--nb-info)`; radio `::after` background → `var(--nb-info)`.
- `.plan-opt-eyebrow` (mode chip) color → `var(--nb-info-ink)`, border → `var(--nb-info-edge)`.
- `.plan-prop-approve` background → `var(--nb-info-grad-btn)`; box-shadow → `rgba(59,130,246,0.32)`; hover background → `linear-gradient(160deg, #3b82f6 0%, #2563eb 60%, #1d4ed8 100%)`.

- [ ] **Step 1: Locate the production `.dt-bubble-bro` rule**

Run: `grep -n '\.dt-bubble-bro {' src/newbro/ui/src/styles/variants-desktop.css`
Expected: one match (the rule defining the bro bubble surface).

- [ ] **Step 2: Replace `.dt-bubble-bro` body to use blue**

Replace the existing rule body so it reads:
```css
.dt-bubble-bro {
  background: var(--nb-info-soft);
  color: var(--nb-ink);
  border: 1px solid var(--nb-info-edge);
  border-bottom-left-radius: 6px;
}
```

- [ ] **Step 3: Locate and update `.thr-bubble-bro` in mobile CSS**

Run: `grep -n '\.thr-bubble-bro {' src/newbro/ui/src/styles/variants-mobile-design.css`
Expected: one match.

Replace its body so it reads:
```css
.thr-bubble-bro {
  background: var(--nb-info-soft);
  color: var(--nb-ink);
  border: 1px solid var(--nb-info-edge);
  border-bottom-left-radius: 6px;
}
```

- [ ] **Step 4: Update the live bubble shadow on mobile**

Run: `grep -n 'thr-bubble-bro.thr-bubble-live' src/newbro/ui/src/styles/variants-mobile-design.css`
Replace the shadow value from coral to blue:
```css
.thr-bubble-bro.thr-bubble-live {
  box-shadow: 0 0 0 3px rgba(59,130,246,0.1);
}
```

- [ ] **Step 5: Update plan proposal & plan options rules in mobile CSS**

For each of the rules listed in the Reference section, replace the coral tokens with the corresponding `--nb-info*` tokens. The simplest way is to run a grep for `plan-prop` and `plan-opt-on` and patch each match in order.

Run: `grep -n 'plan-prop\|plan-opt' src/newbro/ui/src/styles/variants-mobile-design.css`
Apply the swaps per the Reference section above.

- [ ] **Step 6: Update plan proposal & plan options rules in desktop CSS (if present)**

Run: `grep -n 'plan-prop\|plan-opt' src/newbro/ui/src/styles/variants-desktop.css`
Apply the same swaps to any matching rules. If the desktop CSS does not yet contain plan-mode rules (they live only in mobile CSS today), skip this step.

- [ ] **Step 7: Run UI build**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "feat(ui): shift bro bubbles and plan-mode UI to blue (--nb-info-*)"
```

---

## Task 3: Swap flat coral → gradient on action buttons (existing call sites)

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css`
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css`
- Modify: `src/newbro/ui/src/styles/variants-onboarding.css`

**Reference:** Every `background: var(--nb-coral);` on a button/CTA selector in the design diff was changed to `background: var(--nb-coral-grad-btn);`. Every paired `:hover { background: var(--nb-coral-hover); }` was changed to `:hover { background: var(--nb-coral-grad-btn-hover); }`. User chat bubbles (`.dt-bubble-you` / `.thr-bubble-you`) use the flatter `var(--nb-coral-grad)` instead of the button gradient.

Concrete selectors that changed in the design diff (rerun the grep below to discover any production-specific ones):
- `.dt-topvoice-btn-primary`, `.dt-compose-mic-live`, `.dt-text-send`, `.dt-page-action-primary`, `.dt-cmp-send` (round send), the round `.dt-cmp-mic-...` family
- `.thr-send`, `.thr-mic-live`, `.thr-cta-primary` (mobile equivalents — names vary; use grep)
- `.ob-cta` and friends in onboarding CSS
- `.dt-bubble-you` and `.thr-bubble-you` → use `var(--nb-coral-grad)` (not the button gradient)

- [ ] **Step 1: Inventory current flat-coral CTA call sites**

Run: `grep -nE 'background:\s*var\(--nb-coral\);' src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css src/newbro/ui/src/styles/variants-onboarding.css`
Expected: a list of rules (10-25 total) that currently use the flat coral background.

- [ ] **Step 2: Patch each match — buttons use `--nb-coral-grad-btn`**

For each match where the selector is a button / CTA / mic / send / circular action, replace:
- `background: var(--nb-coral);` → `background: var(--nb-coral-grad-btn);`
- The paired `:hover` rule's `background: var(--nb-coral-hover);` → `background: var(--nb-coral-grad-btn-hover);`

Verify each one is a button selector. If the selector is a user message bubble (`.dt-bubble-you`, `.thr-bubble-you`), use `var(--nb-coral-grad)` (the 2-stop) **without** changing the hover (chat bubbles don't have hover state).

- [ ] **Step 3: Run UI build**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 4: Spot-check by running dev server and clicking through**

Run: `cd src/newbro/ui && npm run dev` (in another terminal). Open the artboard, confirm:
- The primary CTA, mic, and send buttons render with a slight 3-stop gradient (not a flat coral).
- User chat bubbles render with a soft 2-stop gradient.

Stop the dev server.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/styles/variants-mobile-design.css src/newbro/ui/src/styles/variants-onboarding.css
git commit -m "feat(ui): swap flat coral to gradient on action buttons and user bubbles"
```

---

## Task 4: Rename input mode labels in UI strings

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx:2442` (single assertion uses `/Always on/`)

**Reference:** `design/app.jsx:213-225` and `design/variants-mobile.jsx:132-140` show the exact new strings.

- [ ] **Step 1: Update the App.test.tsx failing assertion FIRST so the rename is test-driven**

Run: `grep -n 'Always on\|Tap to send' src/newbro/ui/src/__tests__/App.test.tsx`
Replace the matched line so the regex reads `/Hands-free/` instead of `/Always on/`:

```tsx
fireEvent.click(await screen.findByRole("tab", { name: /Hands-free/ }));
```

- [ ] **Step 2: Run the test to confirm it now fails**

Run: `cd src/newbro/ui && npm test -- App.test`
Expected: the test that clicks the `/Hands-free/` tab FAILS because the production tab is still labeled "Always on".

- [ ] **Step 3: Rename labels in ArtboardShell.tsx**

Run: `grep -n 'Tap to send\|Always on' src/newbro/ui/src/ArtboardShell.tsx`
For each match, replace:
- `"Tap to send"` → `"Push to talk"`
- `"Always on"` → `"Hands-free"`
- `"Always on · tap to talk"` → `"Hands-free · tap to talk"`
- `title="Tap to send"` → `title="Push to talk"`
- `title="Always on"` → `title="Hands-free"`

- [ ] **Step 4: Rerun the failing test**

Run: `cd src/newbro/ui && npm test -- App.test`
Expected: the `/Hands-free/` test now PASSES.

- [ ] **Step 5: Run the full UI test suite**

Run: `cd src/newbro/ui && npm test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): rename input-mode labels to Push to talk / Hands-free"
```

---

## Task 5: Rename "node" / "machine" / "executor" → "computer" in UI copy

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx`
- Modify: `src/newbro/ui/src/NewbroShell.tsx`
- Modify: `src/newbro/ui/src/components/newbro/visual.tsx`
- Modify: `src/newbro/ui/src/__tests__/App.test.tsx` (if any rename collides with an assertion)

**Reference:** `design/variants-desktop.jsx` (the diffs in commit `0a89c0f` show every renamed string). UI strings only. Internal TS variable names like `executorNodes`, `nodeName`, `nodeId` and CLI args like `--node-id` and protocol fields like `executor_nodes` stay as-is — this is a copy rename, not a code rename.

Replacements (string-only; only in user-facing JSX strings and prop defaults that surface as strings):

| Old | New |
| --- | --- |
| "Tap to send" | (already done in Task 4) |
| "Always on" | (already done in Task 4) |
| "Connect a node" / "CONNECT A NODE" | "Connect a computer" / "CONNECT A COMPUTER" |
| "Connect your own machines as executor nodes." | "Connect your own computers — a Mac, a spare laptop, anything that stays on." |
| "executor on a machine you trust" | "lives on a computer you trust" (and adjust surrounding sentence per design) |
| "PAUSED · NODE OFFLINE" / "paused · node offline" | "PAUSED · COMPUTER OFFLINE" / "paused · computer offline" |
| "node offline" (as standalone state label) | "computer offline" |
| "needs node" | "needs a computer" |
| "Sending paused while the node is offline." | "Sending paused — reconnect your computer to resume" |
| "reconnect the node" | "reconnect your computer" |
| "the node reconnects" | "that computer reconnects" |
| "Name them, then connect a node" / "Name it, then connect a node" | "Name it, then connect a computer" |
| "Connected nodes" | "Connected computers" |
| "Listening for atlas…" | "Waiting to hear from your computer…" |
| "Run that command on the machine where atlas should work." | "This updates on its own once atlas connects. Nothing else on that computer changes." |
| "Rotate token" | "Get a fresh link" |
| "How does this work?" | "Walk me through it" |
| "Waiting for node…" | "Waiting for your computer…" |
| "Listening on relay.newbro.dev · token valid 9:46" | "We'll detect your computer automatically · link valid 9:46" |
| "Enable local Whisper on the executor node before recording." | "Enable local Whisper on your computer before recording." |
| "Selected Bro's executor node does not support text follow-up." | "Selected Bro's computer doesn't support text follow-up." |
| "Connect the Codex executor before recording." | "Connect Codex on your computer before recording." |
| "Connect the Codex executor before sending." | "Connect Codex on your computer before sending." |
| "{name}'s node is offline. Reconnect it before starting this channel." | "{name}'s computer is offline. Reconnect it before starting this channel." |
| "{name} needs an executor node before voice can target it." | "{name} needs a computer before voice can target it." |
| "Create a worker persona, bind it to a user-owned executor node, and Newbro will generate an install/connect command for the machine that should work for this Bro." | "Create a bro and connect it to a computer you trust. Newbro will give you a one-line install command for that computer." |
| In voice bubble meta line "Voice · 0:06 · transcribed" | "Voice · 0:06 · transcribed · sent to {broName}" |

- [ ] **Step 1: Inventory remaining UI-string occurrences**

Run: `grep -nE 'node offline\|connect a node\|executor node\|Rotate token\|Listening for atlas\|Waiting for node\|machine where|machines as executor\|Connected nodes' src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/components/newbro/visual.tsx`
Expected: ~25 hits across the three files.

- [ ] **Step 2: Apply replacements**

Work through each match using Edit, applying the mapping table above. Do **not** touch:
- TypeScript identifiers (`executorNodes`, `nodeId`, `nodeName`, `ExecutorNodeRecord`, `executor_node_id`, etc.)
- CLI flag strings like `--node-id`
- Protocol field names
- `executor_id: "codex"` and similar
- Comments referencing internal architecture

If a JSX expression interpolates a node name (e.g. `${name}'s node is offline`), update the surrounding template literal to use "computer". If a variable is named `bro.node` for display, leave the variable but adjust the displayed phrase.

- [ ] **Step 3: Inventory test-side collisions**

Run: `grep -nE 'node offline\|connect a node\|Rotate token\|Listening for atlas\|Waiting for node' src/newbro/ui/src/__tests__/App.test.tsx`
For each match, update the asserted string regex to match the new copy.

- [ ] **Step 4: Run the full UI test suite**

Run: `cd src/newbro/ui && npm test`
Expected: all tests pass.

- [ ] **Step 5: Run UI build (typecheck)**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/NewbroShell.tsx src/newbro/ui/src/components/newbro/visual.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): rename node/machine/executor to computer in user-facing copy"
```

---

## Task 6: Add `installOnly` command builder in `session-client.ts`

**Files:**
- Modify: `src/newbro/ui/src/lib/session-client.ts:45-121`
- Modify (if exists): `src/newbro/ui/src/lib/session-client.test.ts`

**Reference:** `design/variants-desktop.jsx:485-516` and `design/variants-onboarding.jsx:155-205` show the design splits the single chained command into two boxes:
1. `curl -fsSL newbro.dev/install.sh | sh`
2. `newbro executor run --token MRElL_T251_gUOuC`

Production already exposes `installConnect` (chained) and `runOnly` (just `newbro executor run …`) via `buildExecutorConnectCommands`. We add the install-only command for the first box.

- [ ] **Step 1: Read the existing command builders**

Run: `sed -n '40,125p' src/newbro/ui/src/lib/session-client.ts`
Expected: see `buildExecutorRunCommand`, `buildExecutorInstallConnectCommand`, `buildExecutorConnectCommands`, and the `ExecutorConnectCommands` interface.

- [ ] **Step 2: Locate or create the test file**

Run: `ls src/newbro/ui/src/lib/session-client.test.ts 2>/dev/null || echo "not found"`
If not found, create it; if found, append.

- [ ] **Step 3: Write the failing test**

Add to `src/newbro/ui/src/lib/session-client.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  buildExecutorConnectCommands,
  buildExecutorInstallOnlyCommand,
} from "./session-client";

describe("buildExecutorInstallOnlyCommand", () => {
  it("returns just the curl install pipeline with no run args", () => {
    const cmd = buildExecutorInstallOnlyCommand();
    expect(cmd).toMatch(/^curl -fsSL .+ \| sh$/);
    expect(cmd).not.toContain("executor run");
    expect(cmd).not.toContain("--token");
  });
});

describe("buildExecutorConnectCommands", () => {
  it("returns installOnly, installConnect, and runOnly", () => {
    const cmds = buildExecutorConnectCommands("node-id-1", "tok-abc");
    expect(cmds.installOnly).toMatch(/^curl -fsSL .+ \| sh$/);
    expect(cmds.installConnect).toContain("curl");
    expect(cmds.installConnect).toContain("executor run");
    expect(cmds.installConnect).toContain("'tok-abc'");
    expect(cmds.runOnly.startsWith("newbro executor run")).toBe(true);
    expect(cmds.runOnly).toContain("'tok-abc'");
  });
});
```

- [ ] **Step 4: Run the test to confirm it fails**

Run: `cd src/newbro/ui && npm test -- session-client`
Expected: FAIL — `buildExecutorInstallOnlyCommand` is not exported.

- [ ] **Step 5: Add the new builder and extend the result type**

In `src/newbro/ui/src/lib/session-client.ts`, change `ExecutorConnectCommands`:

```ts
export interface ExecutorConnectCommands {
  installOnly: string;
  installConnect: string;
  runOnly: string;
}
```

Add a new exported function above `buildExecutorConnectCommands`:

```ts
export function buildExecutorInstallOnlyCommand(): string {
  return ["curl", "-fsSL", NEWBRO_CLI_INSTALL_URL, "|", "sh"].join(" ");
}
```

Extend `buildExecutorConnectCommands` to include the new field:

```ts
export function buildExecutorConnectCommands(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): ExecutorConnectCommands {
  return {
    installOnly: buildExecutorInstallOnlyCommand(),
    installConnect: buildExecutorInstallConnectCommand(nodeId, token, options),
    runOnly: buildExecutorRunCommand(nodeId, token, options),
  };
}
```

- [ ] **Step 6: Rerun the test**

Run: `cd src/newbro/ui && npm test -- session-client`
Expected: PASS.

- [ ] **Step 7: Run UI build to confirm types**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/lib/session-client.ts src/newbro/ui/src/lib/session-client.test.ts
git commit -m "feat(ui): add installOnly command builder for two-step onboarding"
```

---

## Task 7: Restructure the mobile onboarding sheet (`CreateBroSheet`)

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the `CreateBroSheet` component starting near line 1905)
- Modify: `src/newbro/ui/src/styles/variants-onboarding.css` (add new `.ob-sheet-intro`, `.ob-connect-guide` rules; mark Hermes card disabled)

**Reference:** `design/variants-onboarding.jsx:128-235` (full updated sheet body) and `design/variants-onboarding.css:611-660` (new style rules: `.ob-sheet-intro`, `.ob-connect-guide`, etc.).

- [ ] **Step 1: Read the production `CreateBroSheet`**

Run: `sed -n '1905,2020p' src/newbro/ui/src/ArtboardShell.tsx`
Identify where the title, NAME field, EXECUTOR cards, and single connect-command box render today.

- [ ] **Step 2: Read the design source for the new sheet body**

Run: `sed -n '128,235p' design/variants-onboarding.jsx`
This is the complete reference markup the production sheet should mirror (with production data plumbing — see Step 4).

- [ ] **Step 3: Add the new CSS rules to `variants-onboarding.css`**

Append to `src/newbro/ui/src/styles/variants-onboarding.css`:

```css
.ob-sheet-intro {
  margin: 2px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--nb-ink-soft);
  letter-spacing: -0.005em;
  text-wrap: pretty;
}
.ob-connect-guide {
  margin: 0 0 8px;
  padding: 0 2px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--nb-ink-soft);
  letter-spacing: -0.005em;
  text-wrap: pretty;
}
.ob-connect-guide-2 { margin-top: 10px; }

/* Coming-soon disabled state for an executor card */
.ob-exec-card-soon {
  opacity: 0.55;
  cursor: default;
  filter: grayscale(0.15);
}
.ob-exec-card-soon-badge {
  display: inline-block;
  margin-top: 4px;
  padding: 1px 6px;
  font-family: var(--nb-font-mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--nb-ink-muted);
  border: 1px solid var(--nb-line);
  border-radius: 4px;
  background: var(--nb-paper-sub);
}
```

- [ ] **Step 4: Rewrite the `CreateBroSheet` body**

In `src/newbro/ui/src/ArtboardShell.tsx`, locate `CreateBroSheet` (near line 1905). Apply these structural changes:

(a) **Header:** Replace the `<h2 className="ob-sheet-h">Name it, then connect a node.</h2>` with:
```tsx
<h2 className="ob-sheet-h">Set up your first bro</h2>
<p className="ob-sheet-intro">A bro works on a computer you keep on — your Mac, a spare laptop, anything. Three quick steps and it's ready.</p>
```

(b) **NAME eyebrow:** Change `<span className="ob-field-eyebrow">NAME</span>` → `<span className="ob-field-eyebrow">STEP 1 · NAME IT</span>`. Update the field hint to: `Pick one word that's easy to say out loud — you'll talk to it by name. e.g. atlas, scout, forge.`

(c) **EXECUTOR section** — rename to **STEP 2 · AGENT CLIENT**:
- Change the section eyebrow to `<span className="ob-field-eyebrow ob-fieldset-eyebrow">STEP 2 · AGENT CLIENT</span>`.
- Codex card: change the description from whatever it currently says to `<span className="ob-exec-desc">OpenAI&rsquo;s coding agent</span>`.
- Hermes card: add `ob-exec-card-soon` to the class list, remove any click handler so it's non-interactive, and add a "Coming soon" badge:
  ```tsx
  <div className="ob-exec-card ob-exec-card-soon" aria-disabled="true">
    <span className="ob-exec-name">Hermes</span>
    <span className="ob-exec-desc">Open-source agent by Nous Research</span>
    <span className="ob-exec-card-soon-badge">Coming soon</span>
  </div>
  ```
- Below the grid add the field hint:
  ```tsx
  <span className="ob-field-hint">Pick the one you already use — newbro runs your tasks through it. You can switch anytime.</span>
  ```

(d) **CONNECT A NODE section** — rename to **STEP 3 · CONNECT A COMPUTER** and split into two boxes. Replace the existing single command block with this structure (use whatever variable in the component currently holds the connect commands — typically a `commands` object from `buildExecutorConnectCommands`):

```tsx
<div className="ob-fieldset">
  <div className="ob-fieldset-eyebrow-row">
    <span className="ob-field-eyebrow">STEP 3 · CONNECT A COMPUTER</span>
    <span className="ob-fieldset-eyebrow-meta">expires in 9:46</span>
  </div>
  <p className="ob-connect-guide">On the computer where {broName} should work, paste this in a terminal to install newbro:</p>
  <div className="ob-connect">
    <div className="ob-connect-cmd">
      <span className="ob-connect-prompt">$</span>
      <span className="ob-connect-line">{commands?.installOnly ?? "curl -fsSL newbro.dev/install.sh | sh"}</span>
      <button type="button" className="ob-connect-copy" aria-label="Copy install command" onClick={() => commands && void copyCommand(commands.installOnly, "install")}>
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="11" height="11" rx="2"/>
          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
        </svg>
      </button>
    </div>
  </div>
  <p className="ob-connect-guide ob-connect-guide-2">Then start it with your one-time key — we filled in the details for you:</p>
  <div className="ob-connect">
    <div className="ob-connect-cmd">
      <span className="ob-connect-prompt">$</span>
      <span className="ob-connect-line">{commands?.runOnly ?? "newbro executor run --token pending"}</span>
      <button type="button" className="ob-connect-copy" aria-label="Copy connect command" onClick={() => commands && void copyCommand(commands.runOnly, "run")}>
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="11" height="11" rx="2"/>
          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
        </svg>
      </button>
    </div>
    <div className="ob-connect-status">
      <span className="ob-connect-status-pulse" aria-hidden="true"><span /><span /><span /></span>
      <span className="ob-connect-status-text">
        <strong>Waiting to hear from your computer…</strong>
        <span>This updates on its own once {broName} connects. Nothing else on that computer changes.</span>
      </span>
      <span className="ob-connect-time">0:14</span>
    </div>
  </div>
  <div className="ob-connect-meta">
    <button type="button" className="ob-link ob-link-sm">Get a fresh link</button>
    <span className="ob-connect-meta-sep">·</span>
    <button type="button" className="ob-link ob-link-sm">Walk me through it</button>
  </div>
</div>
```

(e) **Footer CTA:** Change the disabled button label from "Waiting for node…" to "Waiting for your computer…".

(f) **Existing `copyCommand` callsite** — if today it calls `copyCommand(commands.installConnect, "install")`, leave any one-shot callers alone but make sure the new buttons use `installOnly` and `runOnly` as shown above.

- [ ] **Step 5: Run UI build**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 6: Spot-check in dev server**

Run: `cd src/newbro/ui && npm run dev`. Open the artboard, navigate to first-run / create-bro flow, confirm: title is "Set up your first bro", STEP 1/2/3 labels render, two command boxes display, Hermes card is greyed out with "Coming soon" badge, and "Get a fresh link" / "Walk me through it" appear in the meta row. Stop the dev server.

- [ ] **Step 7: Run the full UI test suite**

Run: `cd src/newbro/ui && npm test`
Expected: tests pass (existing `mobile install/connect instructions` test from App.test.tsx should still pass; update its asserts if it references old strings).

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-onboarding.css src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): restructure mobile onboarding sheet with STEP 1/2/3 and two-box install"
```

---

## Task 8: Restructure the desktop onboarding modal (`CreateBroModal`) and first-run hero copy

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the desktop `CreateBroModal` and `FirstRunHomeDesktop` / `FirstRunHomeVariant` regions)
- Modify: `src/newbro/ui/src/components/newbro/visual.tsx` (sign-in subtitle)

**Reference:** `design/variants-desktop.jsx:430-560` (CreateBroModal), `design/variants-desktop.jsx:393-410` (FirstRunHomeDesktop hero), `design/variants-onboarding.jsx:60-75` (sign-in subtitle), `design/variants-onboarding.jsx:275-300` (FirstRunHomeVariant hero).

- [ ] **Step 1: Apply the same structural changes from Task 7 to `CreateBroModal`**

Mirror Task 7 Step 4 (a)-(f) in `CreateBroModal`. The modal layout has two columns (modal-col); keep that layout but apply the same step-labels and the same two-box install structure inside the second column. The "TIP" copy at the bottom of the modal updates to:
```
That computer can be anything that stays on — your Mac, a spare laptop, a mini in the closet. {broName} only runs there when you ask it to, and you can move it to another computer anytime.
```

And the footer status line updates to:
```
We'll detect your computer automatically · link valid 9:46
```

- [ ] **Step 2: Update first-run hero copy (both desktop and mobile variants)**

In `ArtboardShell.tsx`, find `FirstRunHomeDesktop` and `FirstRunHomeVariant`. Update the hero subtitle paragraph:

Desktop:
```tsx
A <strong>bro</strong> is a teammate that works on a computer
you trust. Give it a name, connect a computer, and it'll start
working alongside you.
```

Mobile:
```tsx
A <strong>bro</strong> is a teammate that works on a computer
you trust. Give it a name, connect a computer, and it'll show
up here ready to go.
```

- [ ] **Step 3: Update the sign-in subtitle**

In `components/newbro/visual.tsx`, find the sign-in copy:
```
Newbro is a small crew of bros — each one bound to an executor on a machine you trust.
```
Replace with:
```
Newbro is a small crew of bros — each one lives on a computer you trust and keeps working while you talk. No setup headaches.
```

Also update the desktop sign-in bullet from `"Connect your own machines as executor nodes."` to `"Connect your own computers — a Mac, a spare laptop, anything that stays on."`. (Both `ArtboardShell.tsx` `SignInDesktop` and `visual.tsx` may have copies; update both if present.)

- [ ] **Step 4: Run UI build**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 5: Run the full UI test suite**

Run: `cd src/newbro/ui && npm test`
Expected: pass. Update any remaining test asserts that reference the old hero strings.

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/components/newbro/visual.tsx src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): restructure desktop onboarding modal and refresh first-run hero copy"
```

---

## Task 9: Desktop composer — mode toggle gains icons + "Talk mode" eyebrow

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the desktop composer bar component — mirror of `DTComposerBar` in `design/variants-desktop.jsx`)
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (add `.dt-cmp-modewrap`, `.dt-cmp-modewrap-label`, `.dt-cmp-mode-ic`, `.dt-cmp-mode-on-ptt`, `.dt-cmp-mode-on-free`)

**Reference:** `design/variants-desktop.jsx:604-650` (option objects with `icon` SVGs) and `design/variants-desktop.css:3072-3145` (new CSS rules).

- [ ] **Step 1: Add the new CSS rules**

Append to `src/newbro/ui/src/styles/variants-desktop.css`:

```css
.dt-cmp-modewrap {
  display: inline-flex; align-items: center;
  gap: 9px;
}
.dt-cmp-modewrap-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--nb-ink-muted);
  font-family: var(--nb-font-mono, monospace);
  white-space: nowrap;
}
.dt-cmp-mode-ic {
  display: inline-flex;
  opacity: 0.5;
  transition: opacity 0.15s, color 0.15s;
}
.dt-cmp-mode:hover .dt-cmp-mode-ic { opacity: 0.8; }
.dt-cmp-mode-on .dt-cmp-mode-ic { opacity: 1; }
.dt-cmp-mode-on-ptt  .dt-cmp-mode-ic { color: var(--nb-coral); }
.dt-cmp-mode-on-free .dt-cmp-mode-ic { color: var(--nb-live-ink, #10b981); }
```

- [ ] **Step 2: Patch the desktop composer's mode-options array**

In the production desktop composer (search `ArtboardShell.tsx` for the `dt-cmp-mode` class — likely in a component handling text-vs-voice toggle), replace the simple option list with these option objects that include icon JSX:

```tsx
const opts = [
  {
    v: "ptt",
    label: "Push to talk",
    icon: (
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="3" width="6" height="11" rx="3"/>
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
      </svg>
    ),
  },
  {
    v: "free",
    label: "Hands-free",
    icon: (
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="10" y="4" width="4" height="9" rx="2"/>
        <path d="M6.5 8.5a6 6 0 0 0 0 7M17.5 8.5a6 6 0 0 1 0 7"/>
        <path d="M12 17v3"/>
      </svg>
    ),
  },
];
```

- [ ] **Step 3: Wrap the mode-toggle in `.dt-cmp-modewrap` with the eyebrow**

Replace the existing JSX:
```tsx
<div className={`dt-cmp-modes${disabled ? " dt-cmp-modes-off" : ""}`} role="tablist" aria-label="Input mode">
  …existing mode buttons…
</div>
```
with:
```tsx
<div className="dt-cmp-modewrap">
  <span className="dt-cmp-modewrap-label">Talk mode</span>
  <div className={`dt-cmp-modes${disabled ? " dt-cmp-modes-off" : ""}`} role="tablist" aria-label="How you talk to the bro">
    {opts.map((o) => {
      const on = voiceMode === o.v;
      return (
        <button
          key={o.v}
          type="button"
          role="tab"
          aria-selected={on}
          disabled={disabled}
          className={`dt-cmp-mode${on ? ` dt-cmp-mode-on dt-cmp-mode-on-${o.v}` : ""}`}
          onClick={() => !disabled && onMode && onMode(o.v)}
        >
          <span className="dt-cmp-mode-ic" aria-hidden="true">{o.icon}</span>
          <span>{o.label}</span>
        </button>
      );
    })}
  </div>
</div>
```

- [ ] **Step 4: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```
Expected: clean build, tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css
git commit -m "feat(ui): add icons and 'Talk mode' eyebrow to desktop composer mode toggle"
```

---

## Task 10: Desktop composer — move Plan chip inside the composer bar

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (move the Plan chip render so it lives inside the input bar, leading the input)
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (update `.dt-cmp-planchip` and `.dt-cmp-planchip-on` rules per design)

**Reference:** `design/variants-desktop.jsx:688-714` (where `planChip` is defined and placed) and `design/variants-desktop.css:3155-3200` (new chip rules).

- [ ] **Step 1: Update Plan chip CSS to the new on/hover treatment**

In `src/newbro/ui/src/styles/variants-desktop.css`, locate `.dt-cmp-planchip` rules and replace the on-state block:

```css
.dt-cmp-planchip {
  display: inline-flex; align-items: center; gap: 7px;
  flex-shrink: 0;
  padding: 7px 10px 7px 11px;
  margin-left: 2px;
  border-radius: 12px;
  background: var(--nb-paper-sub);
  border: 1px solid var(--nb-line);
  color: var(--nb-ink-soft);
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.01em;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.dt-cmp-planchip:hover {
  background: rgba(0,0,0,0.04);
  color: var(--nb-ink);
  border-color: rgba(0,0,0,0.08);
}
.dt-cmp-planchip-on {
  background: var(--nb-coral-grad-btn);
  border-color: var(--nb-coral);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 4px 12px -5px rgba(255,106,61,0.6);
}
.dt-cmp-planchip-on:hover { border-color: var(--nb-coral); color: #fff; }
.dt-cmp-planchip-on .dt-cmp-planchip-kbd {
  background: rgba(255,255,255,0.22);
  border-color: rgba(255,255,255,0.4);
  color: #fff;
}
```

Also update the composer-bar plan-mode border accent:
```css
.dt-cmp-plan .dt-cmp-bar {
  border-color: var(--nb-coral-border);
}
```
(Drop the `background: var(--nb-coral-tint);` that previously colored the bar — the solid chip now carries the signal.)

- [ ] **Step 2: Define the `planChip` JSX as a local constant and move it inside the bar**

In the composer component, define near the top of the render:

```tsx
const planChip = !disabled && (
  <button
    type="button"
    className={`dt-cmp-planchip${planMode ? " dt-cmp-planchip-on" : ""}`}
    onClick={() => onTogglePlan && onTogglePlan()}
    aria-pressed={planMode}
    title={`Plan mode · Shift+Tab — ${broName} proposes a plan before acting`}
  >
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="9" width="6" height="6" rx="1.5"/>
      <rect x="15" y="4" width="6" height="6" rx="1.5"/>
      <rect x="15" y="14" width="6" height="6" rx="1.5"/>
      <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
    </svg>
    <span className="dt-cmp-planchip-label">Plan{planMode ? " on" : ""}</span>
    <kbd className="dt-kbd dt-cmp-planchip-kbd">⇧⇥</kbd>
  </button>
);
```

- [ ] **Step 3: Remove the Plan chip from its old position (next to the mode toggle in `.dt-cmp-headl`)**

Delete the existing in-header Plan chip render.

- [ ] **Step 4: Render `planChip` inside both bar variants (PTT and free)**

Inside the `voiceMode === "ptt"` JSX block, render `planChip` as the first child of `<div className="dt-cmp-bar">`. Inside the `voiceMode === "free"` JSX block, render `planChip` as the first child of `<div className="dt-cmp-channel …">`.

- [ ] **Step 5: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css
git commit -m "feat(ui): move Plan chip inside the desktop composer bar"
```

---

## Task 11: Desktop composer — press-and-hold PTT mic with inline waveform + hint refresh

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (the composer bar — add recording state + press-and-hold mic + hint text)
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (add `.dt-cmp-rec*`, `.dt-cmp-action*` rules per design)

**Reference:** `design/variants-desktop.jsx:648-880` (state, handlers, recording strip, action buttons). The waveform uses 30 bars driven by a sine function; timer increments every second. Pointer-down arms recording; pointer-up/leave/cancel stops it. While text is non-empty and not recording, the trailing button swaps to a send arrow.

- [ ] **Step 1: Port the CSS rules**

Append to `src/newbro/ui/src/styles/variants-desktop.css` (read `design/variants-desktop.css` for the exact `.dt-cmp-bar-rec`, `.dt-cmp-rec`, `.dt-cmp-rec-dot`, `.dt-cmp-rec-label`, `.dt-cmp-rec-wave`, `.dt-cmp-rec-wave i`, `.dt-cmp-rec-time`, `.dt-cmp-rec-hint`, `.dt-cmp-action`, `.dt-cmp-action-send`, `.dt-cmp-action-mic`, `.dt-cmp-action-mic-on`, `.dt-cmp-action-mic-off`, `.dt-cmp-action-rec` rules — they're a contiguous block of about 100 lines):

Run: `sed -n '/\.dt-cmp-bar-rec/,/^}$/p' design/variants-desktop.css | head -120`

Copy the matched block into the production CSS file, replacing or augmenting any existing rules with the same selectors.

- [ ] **Step 2: Add recording state to the composer**

In the composer component, add at the top of the function body:

```tsx
const [recording, setRecording] = React.useState(false);
const [recSecs, setRecSecs] = React.useState(0);
const recTimer = React.useRef<ReturnType<typeof setInterval> | null>(null);
const startRec: React.PointerEventHandler<HTMLButtonElement> = (e) => {
  if (disabled) return;
  e.preventDefault();
  setRecording(true);
  setRecSecs(0);
  if (recTimer.current) clearInterval(recTimer.current);
  recTimer.current = setInterval(() => setRecSecs((s) => s + 1), 1000);
  // Hook into the existing useVoiceSession start callback if available:
  // onRecordStart?.();
};
const stopRec = () => {
  if (!recording) return;
  if (recTimer.current) clearInterval(recTimer.current);
  setRecording(false);
  setRecSecs(0);
  // onRecordStop?.();
};
React.useEffect(() => () => { if (recTimer.current) clearInterval(recTimer.current); }, []);
const recFmt = `0:${String(recSecs).padStart(2, "0")}`;
const hasText = text.trim().length > 0;
```

If the existing composer wires audio capture via a different prop (e.g. `onMicDown` / `onMicUp` or methods from `useVoiceSession`), call those in the marked spots so press-and-hold drives real audio capture instead of just visuals. The wiring detail to verify before commit: ensure the same start/stop semantics the previous mic button used are still called.

- [ ] **Step 3: Replace the PTT bar JSX with the recording-aware version**

Replace the existing `<div className="dt-cmp-bar">` block with:

```tsx
<div className={`dt-cmp-bar${recording ? " dt-cmp-bar-rec" : ""}`}>
  {planChip}
  {recording ? (
    <div className="dt-cmp-rec">
      <span className="dt-cmp-rec-dot" aria-hidden="true" />
      <span className="dt-cmp-rec-label">Listening…</span>
      <span className="dt-cmp-rec-wave" aria-hidden="true">
        {Array.from({ length: 30 }).map((_, i) => {
          const h = 5 + Math.abs(Math.sin((i + 1) * 0.6)) * 15;
          return <i key={i} style={{ height: h, animationDelay: `${(i % 7) * 0.07}s` }} />;
        })}
      </span>
      <span className="dt-cmp-rec-time">{recFmt}</span>
      <span className="dt-cmp-rec-hint">release to send</span>
    </div>
  ) : (
    <input
      type="text"
      className="dt-cmp-input"
      disabled={disabled}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={handleKey}
      placeholder={
        disabled
          ? `${broName} can't take new messages — reconnect your computer to resume`
          : planMode
            ? `Describe the task — ${broName} will plan it first…`
            : `Hold to talk, or type a message to ${broName}…`
      }
    />
  )}

  {hasText && !recording ? (
    <button
      type="button"
      className="dt-cmp-action dt-cmp-action-send"
      disabled={disabled}
      aria-label="Send message"
      onClick={submit}
    >
      <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 19V5M5 12l7-7 7 7"/>
      </svg>
    </button>
  ) : (
    <button
      type="button"
      className={`dt-cmp-action dt-cmp-action-mic dt-cmp-action-mic-${disabled ? "off" : "on"}${recording ? " dt-cmp-action-rec" : ""}`}
      disabled={disabled}
      aria-label={recording ? "Release to send" : "Hold to talk"}
      title={recording ? "Release to send" : "Press and hold to talk"}
      onPointerDown={startRec}
      onPointerUp={stopRec}
      onPointerLeave={stopRec}
      onPointerCancel={stopRec}
    >
      {recording ? (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
          <rect x="6" y="6" width="12" height="12" rx="3"/>
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="12" rx="3"/>
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
          {disabled && <path d="M3 3l18 18"/>}
        </svg>
      )}
    </button>
  )}
</div>
```

- [ ] **Step 4: Update the hint text**

Replace the existing `<span className="dt-cmp-hint">…</span>` with:

```tsx
<span className="dt-cmp-hint">
  {disabled
    ? <span>Sending paused — reconnect your computer to resume</span>
    : voiceMode === "ptt"
      ? (recording
          ? <span>Recording… release the mic to send</span>
          : hasText
            ? <span>Press <kbd className="dt-kbd">Enter</kbd> to send</span>
            : <span>Hold <kbd className="dt-kbd">Space</kbd> to talk, or type your message</span>)
      : subMode === "silent"
        ? <span>Mic's open — just speak; {broName} replies when you pause</span>
        : <span>Mic's open — {broName} may chime in as you go</span>}
</span>
```

- [ ] **Step 5: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

- [ ] **Step 6: Spot-check by holding the mic in dev server**

Run: `cd src/newbro/ui && npm run dev`. Open the artboard, hold the mic button — confirm:
- The input swaps to the recording strip with a live waveform and ticking timer.
- Releasing returns to the input.
- Typing text causes the trailing button to swap from mic to send arrow.
Stop the dev server.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css
git commit -m "feat(ui): press-and-hold PTT mic with inline waveform on desktop composer"
```

---

## Task 12: Add `recent_execution_details` field to `SessionSnapshot`

**Files:**
- Modify: `src/newbro/protocol/__init__.py` (re-export `TaskExecutionDetailEntry` if not already)
- Modify: `src/newbro/runtime/models.py:34-54`
- Test: `tests/unit/protocol/test_protocol_models.py` (or extend `tests/unit/runtime/test_session_runtime.py`)

**Reference:** Spec §8.2. The blackboard already exposes `list_recent_task_execution_details(task_limit, entry_limit)` returning `dict[task_id, list[TaskExecutionDetailEntry]]`. We mirror that shape on the snapshot.

- [ ] **Step 1: Confirm `TaskExecutionDetailEntry` is exported from `newbro.protocol`**

Run: `grep -n 'TaskExecutionDetailEntry' src/newbro/protocol/__init__.py`
If not present, add it to the `__init__` re-exports alongside `ExecutionRun`, `Task`, etc.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/runtime/test_session_runtime.py`:

```python
@pytest.mark.anyio
async def test_session_runtime_snapshot_carries_recent_execution_details():
    from newbro.protocol import TaskExecutionDetailEntry

    session = create_session_runtime(
        "session-snap-detail",
        model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="request_clarification")}
        ),
        settings=Settings(),
    )

    # Seed two execution-detail entries for a task. The blackboard append API
    # works at the projection layer; the snapshot builder reads via
    # list_recent_task_execution_details.
    entry_a = TaskExecutionDetailEntry(
        detail_id="d-1",
        task_id="task-1",
        run_id="run-1",
        execution_session_id="es-1",
        event_type="PROGRESS",
        text="Looking up flights",
        created_at="2026-05-30T10:00:00Z",
    )
    entry_b = TaskExecutionDetailEntry(
        detail_id="d-2",
        task_id="task-1",
        run_id="run-1",
        execution_session_id="es-1",
        event_type="PROGRESS",
        text="Comparing fares",
        created_at="2026-05-30T10:00:05Z",
    )
    await session.blackboard.append_task_execution_detail(entry_a)
    await session.blackboard.append_task_execution_detail(entry_b)

    snapshot = await session.snapshot(sync_imported_codex_threads=False)

    assert "task-1" in snapshot.recent_execution_details
    entries = snapshot.recent_execution_details["task-1"]
    assert [e.detail_id for e in entries] == ["d-1", "d-2"]
    assert all(isinstance(e, TaskExecutionDetailEntry) for e in entries)
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_runtime_snapshot_carries_recent_execution_details -xvs`
Expected: FAIL — `recent_execution_details` is not yet a field on `SessionSnapshot`.

- [ ] **Step 4: Add the field to `SessionSnapshot`**

In `src/newbro/runtime/models.py`, add the import:

```python
from newbro.protocol import (
    …existing imports…
    TaskExecutionDetailEntry,
)
```

And the field on `SessionSnapshot` (place it next to `executor_capabilities` so projection-only fields cluster together):

```python
class SessionSnapshot(BaseModel):
    …existing fields…
    executor_nodes: list[ExecutorNodeRecord] = Field(default_factory=list)
    recent_execution_details: dict[str, list[TaskExecutionDetailEntry]] = Field(default_factory=dict)
    draft_session: DraftSession | None = None
```

- [ ] **Step 5: Run the test again — it should still fail because `snapshot()` doesn't populate the field yet**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_runtime_snapshot_carries_recent_execution_details -xvs`
Expected: FAIL — `assert "task-1" in snapshot.recent_execution_details` because the field is empty `{}`. (This is the correct intermediate state; Task 13 populates it.)

- [ ] **Step 6: Commit the protocol field (test left failing for Task 13)**

```bash
git add src/newbro/runtime/models.py src/newbro/protocol/__init__.py tests/unit/runtime/test_session_runtime.py
git commit -m "feat(runtime): add recent_execution_details field to SessionSnapshot"
```

---

## Task 13: Populate `recent_execution_details` in `SessionRuntime.snapshot()`

**Files:**
- Modify: `src/newbro/runtime/session.py:1595-1664`

**Reference:** Spec §8.2. The blackboard reader is `Blackboard.list_recent_task_execution_details(task_limit=5, entry_limit=20)`. The spec proposes `entry_limit=8` headroom for a 3-line rolling window; we keep `task_limit` reasonable (e.g. 10) so the UI sees details for any active bro.

- [ ] **Step 1: Add the read call in `snapshot()`**

In `src/newbro/runtime/session.py`, inside `async def snapshot(...)`, after the existing `bro_threads = …` block and before the `return SessionSnapshot(...)` call, add:

```python
recent_execution_details = await self.blackboard.list_recent_task_execution_details(
    task_limit=10,
    entry_limit=8,
)
```

- [ ] **Step 2: Pass it into the `SessionSnapshot` constructor**

Update the `return SessionSnapshot(...)` call to include the new kwarg:

```python
return SessionSnapshot(
    …existing kwargs…
    executor_nodes=await self.executor_node_manager.list_nodes(),
    recent_execution_details=recent_execution_details,
    draft_session=self.draft_manager.active_session,
)
```

- [ ] **Step 3: Run the test — it should now pass**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py::test_session_runtime_snapshot_carries_recent_execution_details -xvs`
Expected: PASS.

- [ ] **Step 4: Run the full session-runtime test file to confirm no regression**

Run: `.venv/bin/python -m pytest tests/unit/runtime/test_session_runtime.py -x`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/runtime/session.py
git commit -m "feat(runtime): populate recent_execution_details on session snapshot"
```

---

## Task 14: Extend UI types with `ExecutionDetailEntry` and `recent_execution_details`

**Files:**
- Modify: `src/newbro/ui/src/types.ts`

**Reference:** Mirror the Python model shape from `TaskExecutionDetailEntry`.

- [ ] **Step 1: Add the new interface**

In `src/newbro/ui/src/types.ts`, add near the existing `ExecutionRun` interface:

```ts
export interface ExecutionDetailEntry {
  detail_id: string;
  task_id: string;
  run_id: string;
  execution_session_id: string;
  event_type: string;          // PROGRESS | PLAN | WAITING_EXECUTOR | BLOCKED | COMPLETED | FAILED | CANCELLED
  text: string;
  created_at: string;
  payload?: Record<string, unknown>;
}
```

- [ ] **Step 2: Add the field to the snapshot interface**

Locate the TypeScript interface for `SessionSnapshot` (mirroring `runtime/models.py SessionSnapshot`). It should be near the `bro_timeline_turns` field. Add:

```ts
recent_execution_details: Record<string, ExecutionDetailEntry[]>;
```

If the existing TS interface uses optional fields for forward-compatibility, mark the field optional with a default at the consuming site instead — pick whichever pattern matches the surrounding fields.

- [ ] **Step 3: Run UI build to confirm types compile**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/types.ts
git commit -m "feat(ui): add ExecutionDetailEntry type and recent_execution_details on SessionSnapshot"
```

---

## Task 15: Adapter exposes `reasoningSteps` and `latestReasoningStep`

**Files:**
- Modify: `src/newbro/ui/src/components/newbro/adapters.ts`
- Test: `src/newbro/ui/src/components/newbro/adapters.test.ts` (create if absent)

**Reference:** Spec §8.4. The adapter joins `turn.task.task_id → recent_execution_details[task_id]`, filters by `event_type ∈ {"PROGRESS", "PLAN"}`, and maps each filtered entry to a `ReasoningStep`. For an in-flight run the newest filtered entry is `"active"`; older are `"done"`; for a terminal run all are `"done"`.

- [ ] **Step 1: Define the view model type**

In `src/newbro/ui/src/components/newbro/adapters.ts` (or `components/newbro/types.ts` if there's a shared types file), add:

```ts
export interface ReasoningStep {
  id: string;
  label: string;
  status: "active" | "done";
  created_at: string;
}
```

- [ ] **Step 2: Write the failing test**

Create `src/newbro/ui/src/components/newbro/adapters.test.ts` (or append to an existing one):

```ts
import { describe, expect, it } from "vitest";
import type { ExecutionDetailEntry, ExecutionRun } from "../../types";
import { buildReasoningStepsForTurn, latestReasoningLabel } from "./adapters";

const entry = (id: string, ev: string, text: string): ExecutionDetailEntry => ({
  detail_id: id,
  task_id: "task-1",
  run_id: "run-1",
  execution_session_id: "es-1",
  event_type: ev,
  text,
  created_at: "2026-05-30T10:00:00Z",
});

const run: ExecutionRun = {
  run_id: "run-1",
  task_id: "task-1",
  execution_session_id: "es-1",
  executor_type: "codex",
  status: "running",
  claimed_by: null,
  run_revision: 0,
  latest_progress_message: null,
  output_summary: null,
  block_reason: null,
  failure_reason: null,
  metadata: {},
};

describe("buildReasoningStepsForTurn", () => {
  it("filters to PROGRESS and PLAN, marks newest active while run is RUNNING", () => {
    const details = [
      entry("a", "PROGRESS", "Looking up flights"),
      entry("b", "BLOCKED",  "Waiting for confirmation"),
      entry("c", "PLAN",     "Will compare three routes"),
      entry("d", "PROGRESS", "Comparing fares"),
    ];
    const steps = buildReasoningStepsForTurn(run, details);
    expect(steps.map((s) => s.id)).toEqual(["a", "c", "d"]);
    expect(steps.at(-1)!.status).toBe("active");
    expect(steps.slice(0, -1).every((s) => s.status === "done")).toBe(true);
  });

  it("marks all done when the run has terminated", () => {
    const completed: ExecutionRun = { ...run, status: "completed" };
    const details = [entry("a", "PROGRESS", "x"), entry("b", "PROGRESS", "y")];
    const steps = buildReasoningStepsForTurn(completed, details);
    expect(steps.every((s) => s.status === "done")).toBe(true);
  });

  it("returns [] for an empty details list", () => {
    expect(buildReasoningStepsForTurn(run, [])).toEqual([]);
  });
});

describe("latestReasoningLabel", () => {
  it("returns the most recent PROGRESS/PLAN text or null", () => {
    expect(latestReasoningLabel([])).toBeNull();
    expect(latestReasoningLabel([entry("a", "BLOCKED", "x")])).toBeNull();
    expect(latestReasoningLabel([
      entry("a", "PROGRESS", "first"),
      entry("b", "PROGRESS", "second"),
    ])).toBe("second");
  });
});
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `cd src/newbro/ui && npm test -- adapters`
Expected: FAIL — functions not exported.

- [ ] **Step 4: Implement the functions**

In `src/newbro/ui/src/components/newbro/adapters.ts`, add:

```ts
const REASONING_EVENT_TYPES = new Set(["PROGRESS", "PLAN"]);

function isRunInFlight(run: ExecutionRun): boolean {
  return run.status === "running" || run.status === "created" || run.status === "waiting_executor";
}

export function buildReasoningStepsForTurn(
  run: ExecutionRun | null | undefined,
  details: ExecutionDetailEntry[] | null | undefined,
): ReasoningStep[] {
  if (!run || !details || details.length === 0) return [];
  const filtered = details.filter((d) => REASONING_EVENT_TYPES.has(d.event_type));
  if (filtered.length === 0) return [];
  const inFlight = isRunInFlight(run);
  const lastIndex = filtered.length - 1;
  return filtered.map((d, i) => ({
    id: d.detail_id,
    label: d.text,
    status: inFlight && i === lastIndex ? "active" : "done",
    created_at: d.created_at,
  }));
}

export function latestReasoningLabel(
  details: ExecutionDetailEntry[] | null | undefined,
): string | null {
  if (!details || details.length === 0) return null;
  for (let i = details.length - 1; i >= 0; i--) {
    if (REASONING_EVENT_TYPES.has(details[i].event_type)) return details[i].text;
  }
  return null;
}
```

Update imports at the top of `adapters.ts` to include `ExecutionDetailEntry`, `ExecutionRun`, and `ReasoningStep`.

- [ ] **Step 5: Rerun the test**

Run: `cd src/newbro/ui && npm test -- adapters`
Expected: PASS.

- [ ] **Step 6: Wire the adapter results into the bro card model**

Locate the existing card-model builder in `adapters.ts` (the function that produces the model consumed by the home bro grid — search for `latestReasoningStep` callsites or for the function producing the model). Add a derived `latestReasoningStep: string | null` on the per-bro model:

```ts
latestReasoningStep: latestReasoningLabel(snapshot.recent_execution_details[bro.activeTaskId ?? ""] ?? null),
```

Use whatever active-task-id field already exists on the bro model. If none, derive from the bro's latest in-flight `BroTimelineTurn`.

- [ ] **Step 7: Run UI build**

Run: `cd src/newbro/ui && npm run build`
Expected: clean build.

- [ ] **Step 8: Commit**

```bash
git add src/newbro/ui/src/components/newbro/adapters.ts src/newbro/ui/src/components/newbro/adapters.test.ts
git commit -m "feat(ui): adapter exposes reasoningSteps and latestReasoningStep"
```

---

## Task 16: Port the live reasoning bubble (desktop)

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (add `.dt-bubble-reason`, `.dt-reason-kicker`, `.dt-reason-orb`, `.dt-reason-step*` block — about 100 lines)
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (replace the working-status JSX with the live reasoning bubble in the desktop turn renderer)

**Reference:** `design/variants-desktop.css:1330-1480` (the new reasoning bubble + step list CSS, starting at the comment "Live reasoning bubble"); `design/variants-desktop.jsx` rendering site for the desktop working turn.

- [ ] **Step 1: Port the CSS block**

Run: `sed -n '/\/\* Live reasoning bubble/,/^}$/p' design/variants-desktop.css | head -160`
Copy that contiguous block (from the `Live reasoning bubble` comment through `@keyframes dt-reason-in`) into `src/newbro/ui/src/styles/variants-desktop.css`, inserted near the other `.dt-bubble-*` rules.

- [ ] **Step 2: Locate the desktop working-status JSX**

Run: `grep -n 'dt-status\|dt-status-title\|dt-status-bar' src/newbro/ui/src/ArtboardShell.tsx`
Identify the block that renders the current desktop progress-bar status card for a working bro (the desktop equivalent of `state === "working"`).

- [ ] **Step 3: Replace the status JSX with the reasoning bubble**

Substitute the existing progress-card JSX with:

```tsx
{reasoningSteps.length > 0 ? (
  <div className="dt-turn dt-turn-bro">
    <div className="dt-bubble dt-bubble-bro dt-bubble-reason">
      <span className="dt-reason-kicker">
        <span className="dt-reason-orb" aria-hidden="true"><span /><span /><span /></span>
        {broName} is reasoning
      </span>
      <ol className="dt-reason-steps">
        {(() => {
          const upto = reasoningSteps.length;
          const WINDOW = 3;
          const startAt = Math.max(0, upto - WINDOW);
          const vis = reasoningSteps.slice(startAt, upto);
          const FADE = [1, 0.55, 0.26];
          return vis.map((s, j) => {
            const dist = vis.length - 1 - j;
            const isLast = dist === 0;
            return (
              <li
                key={s.id}
                className={`dt-reason-step${isLast ? " dt-reason-step-active" : " dt-reason-step-done"}`}
                style={{ opacity: FADE[dist] ?? 0.26 }}
              >
                <span className="dt-reason-step-mark" aria-hidden="true" />
                <span className="dt-reason-step-text">{s.label}</span>
              </li>
            );
          });
        })()}
      </ol>
    </div>
  </div>
) : null}
```

`reasoningSteps` should come from the adapter's per-turn view model (Task 15). If the existing component receives only the older fields, thread the new value through props.

- [ ] **Step 4: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css
git commit -m "feat(ui): live reasoning bubble on desktop replaces working progress card"
```

---

## Task 17: Port the live reasoning bubble (mobile) + `ThrReasoned` collapsed pill

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-mobile-design.css` (add `.thr-reason*`, `.thr-reasoned*` block)
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (replace mobile working-status JSX; add `ThrReasoned` component)

**Reference:** `design/variants-mobile.css:1875-1970` (CSS block — from `/* ── live reasoning bubble` through `.thr-reason-steps-static .thr-reason-text { … }`); `design/variants-mobile.jsx:1242-1276` (`ThrReasoned` component) and `:1485-1525` (working-turn render swap).

- [ ] **Step 1: Port the CSS block**

Run: `sed -n '/\/\* ── live reasoning bubble/,/thr-reason-steps-static .thr-reason-text/p' design/variants-mobile.css`
Copy into `src/newbro/ui/src/styles/variants-mobile-design.css`, inserted near `.thr-bubble-bro`.

- [ ] **Step 2: Add the `ThrReasoned` component**

In `src/newbro/ui/src/ArtboardShell.tsx`, near the other mobile thread helpers, add:

```tsx
function ThrReasoned({ steps }: { steps: ReasoningStep[] }) {
  const [open, setOpen] = React.useState(false);
  if (steps.length === 0) return null;
  return (
    <div className="thr-reasoned">
      <button
        type="button"
        className={`thr-reasoned-toggle${open ? " thr-reasoned-toggle-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 12.5L10 18L20 6"/>
        </svg>
        <span>{open ? "Hide reasoning" : "Reasoned"}</span>
        <svg className="thr-reasoned-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <ol className="thr-reason-steps thr-reason-steps-static">
          {steps.map((s) => (
            <li key={s.id} className="thr-reason-step thr-reason-step-done">
              <span className="thr-reason-mark" aria-hidden="true" />
              <span className="thr-reason-text">{s.label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Replace the mobile working-turn JSX**

Run: `grep -n 'thr-status\|thr-status-head\|thr-status-bar' src/newbro/ui/src/ArtboardShell.tsx`
Locate the mobile working-turn block (`mode === "working"`). Replace its body with:

```tsx
<div className="thr-turn thr-turn-bro">
  <div className="thr-bubble thr-bubble-bro thr-reason">
    <span className="thr-reason-kicker">
      <span className="thr-reason-orb" aria-hidden="true"><span /><span /><span /></span>
      {broName} is reasoning
    </span>
    <ol className="thr-reason-steps">
      {(() => {
        const upto = reasoningSteps.length;
        const WINDOW = 3;
        const startAt = Math.max(0, upto - WINDOW);
        const vis = reasoningSteps.slice(startAt, upto);
        const FADE = [1, 0.55, 0.26];
        return vis.map((s, j) => {
          const dist = vis.length - 1 - j;
          const isLast = dist === 0;
          return (
            <li
              key={s.id}
              className={`thr-reason-step${isLast ? " thr-reason-step-active" : " thr-reason-step-done"}`}
              style={{ opacity: FADE[dist] ?? 0.26 }}
            >
              <span className="thr-reason-mark" aria-hidden="true" />
              <span className="thr-reason-text">{s.label}</span>
            </li>
          );
        });
      })()}
    </ol>
  </div>
  <div className="thr-meta">{broName} · updating live</div>
</div>
```

- [ ] **Step 4: Render `ThrReasoned` above the assistant reply bubble for settled turns**

In the same file, locate the rendering for `reply` (a settled assistant text bubble in the mobile thread). Immediately above the bubble, insert:

```tsx
{reasoningSteps.length > 0 && (
  <ThrReasoned steps={reasoningSteps} />
)}
```

- [ ] **Step 5: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

- [ ] **Step 6: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-mobile-design.css
git commit -m "feat(ui): live reasoning bubble + collapsed Reasoned pill on mobile threads"
```

---

## Task 18: Collapsed "Reasoned ✓" pill on desktop

**Files:**
- Modify: `src/newbro/ui/src/styles/variants-desktop.css` (add `.dt-reason-collapsed*` and `.dt-reason-steps-static`)
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (desktop turn renderer — show the pill above the assistant answer when reasoning steps are present and the turn is settled)

**Reference:** `design/variants-desktop.css:1465-1500` (the `.dt-reason-collapsed*` block); `design/variants-desktop.jsx` settled-turn rendering site.

- [ ] **Step 1: Port the CSS block**

Run: `sed -n '/\/\* Settled \/ history: collapsed/,/dt-answer-text/p' design/variants-desktop.css`
Copy into `src/newbro/ui/src/styles/variants-desktop.css`.

- [ ] **Step 2: Add the desktop collapsed pill JSX**

In the desktop turn renderer, above the settled assistant text bubble, insert:

```tsx
{reasoningSteps.length > 0 && isSettledTurn && (
  <DTReasonCollapsed steps={reasoningSteps} />
)}
```

And define `DTReasonCollapsed` as a small local component (same shape as `ThrReasoned` but with the `dt-` class family):

```tsx
function DTReasonCollapsed({ steps }: { steps: ReasoningStep[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className={`dt-bubble-answer`}>
      <button
        type="button"
        className={`dt-reason-collapsed${open ? " dt-reason-collapsed-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <svg className="dt-reason-collapsed-check" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 12.5L10 18L20 6"/>
        </svg>
        <span>{open ? "Hide reasoning" : "Reasoned"}</span>
        <svg className="dt-reason-collapsed-chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <ol className="dt-reason-steps dt-reason-steps-static">
          {steps.map((s) => (
            <li key={s.id} className="dt-reason-step dt-reason-step-done">
              <span className="dt-reason-step-mark" aria-hidden="true" />
              <span className="dt-reason-step-text">{s.label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
```

`isSettledTurn` is true when the turn's status is `"completed"`, `"failed"`, or `"cancelled"` AND the assistant message has final text. Compute it from the turn view model.

- [ ] **Step 3: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

- [ ] **Step 4: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css
git commit -m "feat(ui): collapsed Reasoned pill on desktop settled turns"
```

---

## Task 19: Remove the progress bar and rewire bro home card to `latestReasoningStep`

**Files:**
- Modify: `src/newbro/ui/src/ArtboardShell.tsx` (delete the working-state progress card render at lines ~504-550 and the bro home-card bar at ~1617-1642)

**Reference:** Spec §8.6. The new reasoning bubble already replaces the working-turn progress card. The bro home card should now show `latestReasoningStep` (with fallback to `progressLabel`) plus a small animated 3-dot indicator while a turn is in flight.

- [ ] **Step 1: Delete the working-state progress card helper**

Run: `sed -n '500,560p' src/newbro/ui/src/ArtboardShell.tsx`
Identify the helper that renders the `*-status` block (likely a function named like `renderStatusCard` or inline in a `working` branch). Remove it from the working-turn render path. Both the mobile and desktop working-turn paths should now use the reasoning bubble from Tasks 16/17.

- [ ] **Step 2: Rewire the bro home card**

Run: `grep -n 'dt-bro-card-pct\|dt-bro-card-bar\|dt-bro-card-bar-fill' src/newbro/ui/src/ArtboardShell.tsx`
Replace the `%` + bar render with:

```tsx
{state === "working" && bro.latestReasoningStep ? (
  <div className="dt-bro-card-reasoning">
    <span className="dt-bro-card-reasoning-orb" aria-hidden="true"><span /><span /><span /></span>
    <span className="dt-bro-card-reasoning-text">{bro.latestReasoningStep}</span>
  </div>
) : state === "working" && bro.progressLabel ? (
  <div className="dt-bro-card-reasoning">
    <span className="dt-bro-card-reasoning-orb" aria-hidden="true"><span /><span /><span /></span>
    <span className="dt-bro-card-reasoning-text">{bro.progressLabel}</span>
  </div>
) : null}
```

- [ ] **Step 3: Add small CSS rules for the new bro-card reasoning row**

Append to `src/newbro/ui/src/styles/variants-desktop.css`:

```css
.dt-bro-card-reasoning {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11.5px;
  color: var(--nb-info-ink);
  letter-spacing: -0.005em;
}
.dt-bro-card-reasoning-orb {
  display: inline-flex; align-items: center; gap: 2px;
  flex-shrink: 0;
}
.dt-bro-card-reasoning-orb span {
  width: 3.5px; height: 3.5px;
  border-radius: 50%;
  background: var(--nb-info);
  opacity: 0.35;
  animation: dt-working-bounce 1.25s ease-in-out infinite;
}
.dt-bro-card-reasoning-orb span:nth-child(2) { animation-delay: 0.16s; }
.dt-bro-card-reasoning-orb span:nth-child(3) { animation-delay: 0.32s; }
.dt-bro-card-reasoning-text {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  max-width: 220px;
}
```

(`@keyframes dt-working-bounce` already exists from Task 16's CSS port.)

- [ ] **Step 4: Run UI build and tests**

```bash
cd src/newbro/ui && npm run build && npm test
```

Fix any test failures that asserted on the removed progress percent (`/\d+%/` regexes etc.) — they should now expect the reasoning-step text instead.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/ArtboardShell.tsx src/newbro/ui/src/styles/variants-desktop.css src/newbro/ui/src/__tests__/App.test.tsx
git commit -m "feat(ui): remove progress bar and surface latestReasoningStep on bro cards"
```

---

## Task 20: Append a memory note to `docs/memories.md`

**Files:**
- Modify: `docs/memories.md`

**Reference:** AGENTS.md project-memory rules — short, factual, adopted behavior.

- [ ] **Step 1: Append the note**

Add a new bullet to the end of `docs/memories.md`:

```markdown
- 2026-05-30 — UI reasoning bubble. The session snapshot now projects `recent_execution_details: dict[task_id, list[TaskExecutionDetailEntry]]` (capped per task) so the UI can render a rolling reasoning stream during a turn. Source data is the existing executor `PROGRESS`/`PLAN` events; no Communication Brain change, no new websocket event types.
```

- [ ] **Step 2: Commit**

```bash
git add docs/memories.md
git commit -m "docs: note reasoning-detail projection on session snapshot"
```

---

## Self-Review

Run this against the spec before declaring done:

**Spec coverage**
- §4 Tokens & color — Tasks 1, 2, 3. ✓
- §5 Copy rename — Tasks 4, 5. ✓
- §6 Onboarding restructure — Tasks 6, 7, 8. ✓
- §7 Composer redesign — Tasks 9, 10, 11. ✓
- §8 Reasoning stream — Tasks 12, 13 (backend), 14, 15, 16, 17, 18, 19 (UI). ✓
- §9 Phase 7 memory note — Task 20. ✓
- §10 Risks — PTT wiring flagged in Task 11 Step 2; Hermes is non-clickable per Task 7 Step 4(c); cap size `N=8` set in Task 13.

**Placeholder scan** — no "TBD", "implement later", or unspecified handling. Each task has either complete code or explicit per-line patch instructions plus a reference range.

**Type consistency**
- `ReasoningStep { id; label; status: "active"|"done"; created_at }` defined in Task 15, consumed by Tasks 16, 17, 18.
- `ExecutionDetailEntry` defined in Task 14, consumed by Task 15.
- `recent_execution_details: dict[str, list[TaskExecutionDetailEntry]]` defined in Task 12 (Python) and Task 14 (TS); same key shape (task_id) on both sides.
- `installOnly: string` added to `ExecutorConnectCommands` in Task 6, consumed by Tasks 7 and 8.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-30-design-update-port.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
