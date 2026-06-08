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
- **Capability reporting channel** already carries per-executor facts, but
  through **two distinct models** with a manual copy between them:
  `ExecutorCapabilities` (`executors/core/capabilities.py`, executor-internal) is
  hand-copied by `ExecutorNodeService._descriptor` (`executors/node/service.py:1135`)
  into the wire model `ExecutorNodeExecutor` (`protocol/executor_node.py:10`),
  carried in `RegisterNodeMessage.executors` → node
  `connected_executor_capabilities` → snapshot `executor_capabilities`
  (`runtime/models.py`) → `BroExecutorCapabilitySummary` per bro. Capabilities
  reach the backend **only at `register_node`** — `node_status`
  (`api/ws/executors.py:81`) is acked but does not update registry state.
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
 skills/list ──────────────►  CodexExecutor.skills_list()  ─►  ExecutorCapabilities.skills
                              + ExecutorNodeExecutor.skills  → ExecutorNodeRecord ───────────► snapshot.executor_capabilities
 skills/changed (notif) ────►  node_capabilities message ───►  registry update + snapshot     → BroExecutorCapabilitySummary.skills
                                                                refresh (no reconnect)            → per-bro picker catalog

 turn/start input:
  [{type:text,"$<name> …"},    ◄── outbound_metadata["skill"] ◄── instruction {skill}        ◄── composer: chosen skill
   {type:skill,name,path}]         (mirrors plan_mode)                                            rides on the turn
                                                                 task.metadata["skill"] ───────► timeline "skill pill"
```

## Section 1 — Data model & protocol

New shared model `ExecutorSkill` (lean — carries **no** instruction bodies, to
respect the snapshot-size constraint that previously bit the Cardputer client):

```
name: str                 # codex skill identifier; used for the "$name" marker + skill input item
display_name: str         # interface.displayName, falls back to name
description: str          # interface.shortDescription or description
path: str | None          # absolute SKILL.md path, IF skills/list returns it (see "Open questions").
                          #   When present, enables full-instruction activation via a skill input item.
                          #   When absent, the turn uses marker-only activation ($name) — see §3.
enabled: bool
dependencies: list[ExecutorSkillDependency]   # structured, advisory: required tools / MCP servers
```

`ExecutorSkillDependency` is modeled as a structured object (e.g.
`{kind, name}` or an opaque pass-through dict), **not** `list[str]` — the
app-server reports structured dependency metadata. The exact shape is pinned by
the captured fixture (see Testing + Open questions); until then it is carried as
an opaque `dict[str, object]` so we neither lose data nor over-commit to a shape
we have not observed.

**The capability snapshot path crosses THREE models, not one.** "Rides the
existing capability path" requires updating each, plus the hand-written copy
between them — otherwise skills are discovered on the node but never reach the
backend or the UI snapshot:

1. `ExecutorCapabilities` (`executors/core/capabilities.py`) — the executor's
   internal capability object. Add `skills: list[ExecutorSkill] = []`.
2. `ExecutorNodeExecutor` (`protocol/executor_node.py:10`) — the **wire model**
   carried in `RegisterNodeMessage.executors` and
   `ExecutorNodeRecord.connected_executor_capabilities`. This is a *separate*
   model. Add `skills: list[ExecutorSkill] = []`, and update the manual
   field-by-field copy in `ExecutorNodeService._descriptor`
   (`executors/node/service.py:1135`) to carry skills across. The
   `ExecutorNodeConnectionView` copy in
   `runtime/executor_node_manager.py:1003` is a `model_copy(deep=True)` and
   needs no change once the field exists.
3. `BroExecutorCapabilitySummary` (`runtime/models.py:57`) — the per-bro
   projection the UI reads. Add `skills: list[ExecutorSkill] = []`, populated in
   `session.py` where `codex` capability is already projected (~line 440), so the
   picker reads `bro.executor_node.codex.skills`.

**Turn metadata**, carried like `plan_mode` (which rides
`instruction.metadata["plan_mode"]` / `command.metadata`, not a typed field):
- Instruction request gains optional `skill = {name, path}` (alongside
  `planMode`).
- `direct_turn_starter` writes
  `outbound_metadata["skill"] = {name, path, display_name}`.
- Persisted onto `task.metadata["skill"]`, projected back into the timeline so
  the bubble renders a **skill pill** (same plumbing pattern as
  `_mark_timeline_message_plan_mode`), and **only after** the skill is validated
  against the bro's current catalog (see §3 / §5).
- Skill and plan-mode are **independent and combinable** (run a skill in plan
  mode), matching the prototype's coexisting lead-cluster chips.

## Section 2 — Discovery (executor → backend)

- `CodexClient.skills_list(cwds, force_reload=False)` calls `skills/list` with the
  bro's working directory as `cwds`.
- `CodexExecutor` maps the response into `ExecutorCapabilities.skills`, carrying
  `enabled` through (UI greys out disabled skills — see §5). `CodexExecutor`
  already exposes `refresh_capabilities()` (`executor.py:85`), which
  `_descriptor` calls at descriptor-build time — `skills_list` is invoked there
  so the catalog is populated whenever capabilities are (re)built.
- **Freshness requires a capability-update message — the current protocol has
  none.** Capabilities only reach the backend at `register_node`; `node_status`
  is validated and acked but does **not** update registry state
  (`api/ws/executors.py:81`). So `skills/changed` cannot simply "re-report".
  This spec adds an explicit node→backend message:
  - New `NodeCapabilitiesMessage { type:"node_capabilities", node_id,
    executors: list[ExecutorNodeExecutor] }` sent by the node when capabilities
    change (debounced on `skills/changed`).
  - Backend handler in `_handle_control_message` updates the registry/connection
    state for the node and triggers a snapshot refresh, so the new catalog flows
    to the UI without a reconnect.
  - (Alternative considered: have the node re-send `register_node`. Rejected —
    `register_node` carries auth/registration semantics and re-running it for a
    capability delta conflates two concerns.)
- `acpx` / `mock` / `hosted` adapters report `skills: []` (no behavior change).
  The picker is Codex-only for now, gated on `bro.executor_node.codex` present.

## Section 3 — Selection & execution (turn activation)

**Activation primitive.** `CodexClient.turn_start` gains an optional
`skill: {name, path}`. When present:
- If `path` is known: append a second input item `{type:"skill", name, path}`
  **and** prefix the prompt with the `$<name>` marker, so Codex injects the full
  skill instructions server-side (the documented behavior).
- If `path` is unknown (`skills/list` did not return it — see Open questions):
  **marker-only activation** — prefix the prompt with `$<name>` and send no skill
  input item. This relies on the model resolving the skill rather than
  server-side injection. This is an explicit, documented tradeoff, not a silent
  degrade; the implementer must confirm which mode the real app-server requires
  via the captured fixture.

**Propagation chain (must be threaded explicitly at every hop — the API accepts
`plan_mode` only today).** Skill rides the same metadata carriers as `plan_mode`:

```
ExecutorTextInstructionRequest.skill            (api/routes/executor_text.py:15 — NEW field)
  → session.submit_executor_text_instruction(skill=…)   (session.py — NEW param)
  → ExecutorTextInstruction.metadata["skill"]    (protocol/executor_node.py:257 — via metadata)
  → direct_turn_starter outbound_metadata["skill"]
  → StartCodexTurnCommand.metadata["skill"] / DispatchTextInstructionCommand
  → applied at ALL THREE codex turn_start sites:
       • CodexExecutor.run_task                 (executor.py:362  — reads task.metadata)
       • CodexExecutor.handle_text_instruction  (executor.py:417  — reads instruction.metadata)
       • CodexExecutor.start_turn_request        (executor.py:480 → _turn_start_for_request:920)
```

Each turn_start site already reads `*.metadata["plan_mode"]` independently; skill
is read from the same metadata at each site and passed into the activation
primitive. `_turn_start_for_request` / `_collaboration_kwargs_for_turn` are the
shared helpers to extend so plan-mode + skill compose in one call.

**Vanished skill — observable contract (validate before write, no fallback that
pretends success).** Per the repo golden rules:
1. Before a turn runs, the runtime validates the chosen skill against the bro's
   **current** catalog (the snapshot used to render the picker).
2. If the skill is gone (uninstalled/disabled between pick and send): the runtime
   does **not** write `skill` into `task.metadata`, does **not** render a skill
   pill, and runs the plain turn.
3. It surfaces a defined, non-fatal notice on that turn (an attention/notice item
   stating "Skill <name> is no longer available; ran without it"), so the UI
   never implies the skill ran.
4. Tested explicitly: metadata/pill absent + notice present on the vanished-skill
   path (see Testing).

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

- **Fixture first:** capture a real `skills/list` response (and a `skills/changed`
  notification) from the installed Codex app-server into
  `docs/protocol/fixtures/` (e.g. `codex-skills-list-sample.jsonl`). This pins
  whether `path` is present and the real `dependencies` shape; all adapter
  mapping tests replay against it rather than against prose-inferred shapes.
- **Adapter unit:** `skills_list` request/response mapping (against the fixture);
  `turn_start` builds the `{type:"skill"}` input item + `$name` marker when `path`
  is present, and marker-only when it is not; `skills/changed` triggers the
  `node_capabilities` message.
- **Protocol/wire unit:** `ExecutorNodeExecutor` round-trips `skills`;
  `_descriptor` copies skills across; `node_capabilities` message validates and
  updates registry state (`api/ws/executors.py`).
- **Runtime unit:** skill threads through API → `submit_executor_text_instruction`
  → instruction/command metadata; `direct_turn_starter` writes
  `outbound_metadata["skill"]`; **each** of the three turn_start sites applies the
  skill; task metadata + timeline projection render the skill pill; plan-mode +
  skill combine; **vanished-skill contract** — no metadata, no pill, notice
  present (alongside `test_session_runtime.py`).
- **Capability/snapshot:** `executor_capabilities` surfaces `skills`;
  `BroExecutorCapabilitySummary.skills` populated; `node_capabilities` refreshes
  the snapshot without reconnect.
- **Web unit:** picker reads catalog from snapshot (not hardcoded); `/` filter;
  selection rides on `submitExecutorTextInstruction`; pill renders from timeline
  metadata; chip hidden when empty; disabled skills greyed. Target the new test
  files, not the flaky full `App.test.tsx` suite.
- **Docs:** add a stable doc under `docs/protocol/` (skill discovery + activation
  contract) and a one-line `docs/memories.md` note, per `AGENTS.md`.

## Open questions (resolve during implementation)

1. **Does the installed `skills/list` return `path`?** The public sample shows
   `path` only in the *activation* input-item example, not the list response.
   Resolution: capture the fixture (Testing) and pin it. `ExecutorSkill.path` is
   optional and §3 defines marker-only activation as the fallback; the fixture
   decides which path the implementation takes.
2. **Real `dependencies` shape.** Modeled as structured/opaque
   (`dict[str, object]` pass-through) until the fixture pins it; do not collapse
   to `list[str]`.
3. **`cwds` for discovery.** Confirm the bro's working directory used for
   `skills/list` matches the cwd Codex turns run in, so the discovered catalog is
   the one actually activatable for that bro.

## Out of scope

- Skill discovery for non-Codex executors (acpx/mock/hosted).
- Per-skill icons / custom artwork.
- Editing, installing, or configuring skills from the UI
  (`skills/config/write`).
- Multiple skills per turn (one skill rides one turn).
- Voice-mode skill selection (composer chip is text/PTT composer first; voice
  parity is a follow-up).
```
