# Skill picker (desktop + mobile) — design

**Date:** 2026-06-08
**Status:** Approved design, pre-implementation
**Design reference:** `prototypes/design/variants-desktop.jsx` and `variants-mobile.jsx` (the "active session" artboards), committed in `5b99bb0 feat: update design`.

## Summary

Add a skill picker to the active-session composer on both desktop and mobile.
A skill is a real, agent-native **Codex skill** (a `SKILL.md` package the Codex
app-server already understands). Skills are **discovered per-executor** — each
connected computer reports the skills it has installed — and a chosen skill
**rides along with the next message**, activating that skill for the turn.

The visual design is settled by the prototype. This spec covers the meaning,
data contract, and end-to-end wiring needed to make the prototype's picker real.

### Decisions

- **Skill semantics:** real packaged capability (not UI-only metadata, not a
  Newbro-owned prompt recipe).
- **Catalog source:** discovered per-executor, surfaced through the existing
  capability snapshot.
- **Skill unit:** agent-native Codex skills via the app-server
  ([`skills/list`](https://developers.openai.com/codex/app-server#skills),
  `skills/changed`, skill input items).
- **Freshness:** snapshot + `skills/changed` (Approach A). No new fetch endpoint.
- **Scope:** one spec, end-to-end.

## Background — what already exists

- **Prototype UI** (`prototypes/design/`): desktop popover (`DTSkillMenu`) with a
  `Skill` chip, a selected "skill pill", and an inline `/`-to-filter trigger;
  mobile bottom sheet (`ThrSkillSheet`). Both use a hardcoded `SKILLS` list and a
  "skill rides one turn" model. This is the visual source of truth.
- **`plan_mode` is the template.** The real product already ships plan mode end
  to end and the skill feature mirrors it at every layer:
  - Composer chip → `submitExecutorTextInstruction({ planMode })`
    (`clients/web/src/ArtboardShell.tsx`).
  - `direct_turn_starter` writes `outbound_metadata["plan_mode"]`
    (`src/newbro/runtime/direct_turn_starter.py`).
  - `direct_executor` persists it onto `task.metadata["plan_mode"]`
    (`src/newbro/runtime/direct_executor.py`).
  - Timeline projection re-marks the user message
    (`_mark_timeline_message_plan_mode`,
    `src/newbro/runtime/bro_detail_thread_helpers.py`).
  - `CodexClient.turn_start` maps it to `collaborationMode: "plan"`
    (`src/newbro/executors/adapters/codex/client.py`).
- **Capability reporting channel** already carries per-executor facts:
  `ExecutorCapabilities` (`src/newbro/executors/core/capabilities.py`) →
  node `connected_executor_capabilities` → snapshot `executor_capabilities`
  (`src/newbro/runtime/models.py`) → `BroExecutorCapabilitySummary` per bro.
- **Codex app-server skills contract:**
  - `skills/list` params `{cwds, forceReload, perCwdExtraUserRoots}`; each skill
    has `name`, `description`, `enabled`, optional `interface.{displayName,
    shortDescription}`, optional `dependencies`.
  - `skills/changed` notification when watched skill files change.
  - Activation: add a `{type:"skill", name, path}` input item to `turn/start`
    and include the `$<skill-name>` marker in the user text; the server injects
    full skill instructions.
  - `turn/start` already accepts an `input` array (today a single text item).

## End-to-end shape

```
Codex app-server                Newbro executor node           Backend                          Web UI
 skills/list ──────────────►  CodexExecutor.list_skills()  ─►  ExecutorCapabilities.skills ──► snapshot.executor_capabilities
 skills/changed (notif) ────►  re-report                                                         → per-bro picker catalog

 turn/start input:
  [{type:text,"$<name> …"},    ◄── outbound_metadata["skill"] ◄── instruction {skill}        ◄── composer: chosen skill
   {type:skill,name,path}]         (mirrors plan_mode)                                            rides on the turn
                                                                 task.metadata["skill"] ───────► timeline "skill pill"
```

## Section 1 — Data model & protocol

New shared model `ExecutorSkill` (lean — carries **no** instruction bodies, to
respect the snapshot-size constraint that previously bit the Cardputer client):

```
name: str             # codex skill identifier; used for "$name" marker + skill input item
display_name: str     # interface.displayName, falls back to name
description: str       # interface.shortDescription or description
path: str             # absolute SKILL.md path — required to build the turn input item
enabled: bool
dependencies: list[str]   # advisory: tools/MCP the skill needs
```

- Add `skills: list[ExecutorSkill] = []` to `ExecutorCapabilities`
  (`executors/core/capabilities.py`). Rides the existing
  `connected_executor_capabilities` → `executor_capabilities` snapshot path.
- Add `skills: list[ExecutorSkill] = []` to `BroExecutorCapabilitySummary`
  (`runtime/models.py`) so the per-bro picker reads
  `bro.executor_node.codex.skills`.
- **Turn metadata**, carried like `plan_mode`:
  - Instruction request gains optional `skill = {name, path}` (alongside
    `planMode`).
  - `direct_turn_starter` writes
    `outbound_metadata["skill"] = {name, path, display_name}`.
  - Persisted onto `task.metadata["skill"]`, projected back into the timeline so
    the bubble renders a **skill pill** (same plumbing pattern as
    `_mark_timeline_message_plan_mode`).
- Skill and plan-mode are **independent and combinable** (run a skill in plan
  mode), matching the prototype's coexisting lead-cluster chips.

## Section 2 — Discovery (executor → backend)

- `CodexClient.skills_list(cwds, force_reload=False)` calls `skills/list` with the
  bro's working directory as `cwds`.
- `CodexExecutor` maps the response into `ExecutorCapabilities.skills`, carrying
  `enabled` through (UI greys out disabled skills — see §5).
- Subscribe to the `skills/changed` notification → re-run `skills_list` and
  re-report capabilities. Keeps the catalog fresh with no UI fetch.
- `acpx` / `mock` / `hosted` adapters report `skills: []` (no behavior change).
  The picker is Codex-only for now, gated on `bro.executor_node.codex` present.

## Section 3 — Selection & execution (turn activation)

- `CodexClient.turn_start` gains an optional `skill: {name, path}`. When present:
  append a second input item `{type:"skill", name, path}` and prefix the prompt
  text with the `$<name>` marker, so Codex injects full skill instructions
  server-side.
- Routing mirrors `plan_mode` end to end: composer →
  `submitExecutorTextInstruction({ skill })` → `direct_turn_starter` →
  `direct_executor` → `CodexExecutor` turn run.
- **Vanished skill:** if the turn targets a bro whose current catalog no longer
  contains the chosen skill (uninstalled/disabled between pick and send), the
  runtime drops the skill, runs the plain turn, and surfaces a **non-fatal
  notice**. Per the repo golden rules: no silent fallback that pretends the skill
  ran.

## Section 4 — UI (port the prototype to the real composer)

- **Catalog source:** replace the hardcoded `SKILLS` / `THR_SKILLS` arrays with
  the per-bro list from `bro.executor_node.codex.skills`. Map
  `display_name`/`description` into the existing row markup.
- **Icons:** Codex skills ship no icons → use the single generic
  `SKILL_DEFAULT_ICON` glyph for every row.
- **Desktop** (`DesktopComposerBar`, `ArtboardShell.tsx`): port the lead cluster —
  `Skill` chip ↔ selected pill, the `DTSkillMenu` popover, and the inline
  `/`-to-filter trigger (`onInputChange`, `handleKey`). Sits beside the existing
  `planChip`.
- **Mobile** (mobile composer, `ArtboardShell.tsx`): port `ThrSkillSheet` bottom
  sheet + chip/pill + `/` trigger.
- **State:** `selectedSkill` lives in composer state; cleared after send (one
  skill rides one turn). Changing the active bro clears it (catalog is per-bro).
- **Hint text:** Codex skills have no `hint` field → generic
  "Running with {display_name}…".
- **Empty/unavailable:** if the bro has no Codex node or an empty catalog, hide
  the Skill chip entirely (not shown disabled), matching the prototype's hidden
  lead cluster when offline.

## Section 5 — Edge cases & error handling

- **No skills / non-Codex bro:** chip hidden; `/` does nothing special.
- **Node offline:** lead cluster hidden (existing `disabled` behavior).
- **Disabled skill:** shown greyed/non-selectable (carry `enabled` through).
- **`skills/list` fails on the node:** report `skills: []` (+ optional
  `availability_reason`); do not crash capability reporting. Picker shows no
  skills.
- **Skill vanished between pick and send (§3):** drop skill, run plain turn,
  emit a non-fatal notice; never claim the skill ran.
- **Snapshot size:** `ExecutorSkill` carries no instruction bodies; cap an
  unexpectedly large catalog (e.g. first N) to protect the snapshot contract.

## Section 6 — Testing

- **Adapter unit:** `skills_list` request/response mapping; `turn_start` builds
  the `{type:"skill"}` input item + `$name` marker; `skills/changed` triggers
  re-report.
- **Runtime unit:** `direct_turn_starter` writes `outbound_metadata["skill"]`;
  task metadata + timeline projection render the skill pill; plan-mode + skill
  combine; vanished-skill drop path (alongside `test_session_runtime.py`).
- **Capability/snapshot:** `executor_capabilities` surfaces `skills`;
  `BroExecutorCapabilitySummary.skills` populated.
- **Web unit:** picker reads catalog from snapshot (not hardcoded); `/` filter;
  selection rides on `submitExecutorTextInstruction`; pill renders from timeline
  metadata; chip hidden when empty. Target the new test files, not the flaky
  full `App.test.tsx` suite.
- **Docs:** add a stable doc under `docs/protocol/` (skill discovery + activation
  contract) and a one-line `docs/memories.md` note, per `AGENTS.md`.

## Out of scope

- Skill discovery for non-Codex executors (acpx/mock/hosted).
- Per-skill icons / custom artwork.
- Editing, installing, or configuring skills from the UI
  (`skills/config/write`).
- Multiple skills per turn (one skill rides one turn).
- Voice-mode skill selection (composer chip is text/PTT composer first; voice
  parity is a follow-up).
```
