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
- **Freshness:** snapshot, catalog **loaded once at executor start** and carried
  on the existing `register_node` payload; refreshed on executor reconnect. No new
  fetch endpoint, no `skills/changed` wiring, no new protocol message in v1.
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
- **Codex app-server skills contract — verified against codex-cli 0.137.0** on
  2026-06-08 (fixture: `docs/protocol/fixtures/codex-skills-list-sample.json`):
  - `skills/list` params `{cwds, forceReload, perCwdExtraUserRoots}`.
  - **Response is grouped per cwd:** `{data: [{cwd, skills: [...], errors: [...]}]}`.
    The mapping must flatten across groups, dedupe by `(name, path)`, and surface
    per-cwd `errors`.
  - **Each skill** has: `name`, `description` (long trigger text), `path`
    (absolute `SKILL.md` path — **always present**), `scope` (`"user"`|`"system"`),
    `enabled` (bool). Optional `interface` = `{displayName, shortDescription,
    iconSmall, iconLarge, brandColor, defaultPrompt}` where `iconSmall`/`iconLarge`
    are **node-local file paths** (often non-null) and `defaultPrompt` is
    UI-friendly prompt text. A few skills also carry a **top-level**
    `shortDescription` (no `interface`). `dependencies` is **structured** (e.g.
    `{"tools": [{"type":"mcp","value":…,"url":…}]}`), **not** `list[str]`, and is
    rare (advisory).
  - `skills/changed` notification when watched skill files change.
  - Activation: add a `{type:"skill", name, path}` input item to `turn/start`
    and include the `$<skill-name>` marker in the user text; the server injects
    full skill instructions. (`defaultPrompt` values literally use the `$name`
    form, confirming the marker convention.)
  - `turn/start` already accepts an `input` array (today a single text item).
  - **Size:** a real one-bro catalog was 55 skills / ~40 KB raw; a lean
    projection is ~15 KB. The snapshot must carry the lean projection (below),
    not the raw response.

## End-to-end shape

```
Codex app-server                Newbro executor node           Backend                          Web UI
 skills/list ──────────────►  CodexExecutor.skills_list()  ─►  ExecutorCapabilities.skills
 (once, at executor start)    + cached on executor           + ExecutorNodeExecutor.skills
                              → register_node payload ───────► ExecutorNodeRecord ───────────► snapshot.executor_capabilities
                                                                                              → BroExecutorCapabilitySummary.skills
                                                                                                → per-bro picker catalog
                                (refresh = executor reconnect; no live skills/changed wiring in v1)

 turn/start input:
  [{type:text,"$<name> …"},    ◄── outbound_metadata["skill"] ◄── instruction {skill}        ◄── composer: chosen skill
   {type:skill,name,path}]         (mirrors plan_mode)                                            rides on the turn
                                                                 task.metadata["skill"] ───────► timeline "skill pill"
```

## Section 1 — Data model & protocol

New shared model `ExecutorSkill` — the **lean snapshot projection** (carries no
instruction bodies and not the long `description`, to respect the snapshot-size
constraint that previously bit the Cardputer client; ~15 KB vs ~40 KB raw for a
55-skill catalog):

```
name: str            # codex skill identifier; used for the "$name" marker + skill input item
display_name: str    # interface.displayName → falls back to name
description: str     # interface.shortDescription → top-level shortDescription → description[:160]
hint: str | None     # interface.defaultPrompt — drives the composer placeholder (see §4)
path: str            # absolute SKILL.md path; always returned by skills/list → enables skill input item
enabled: bool        # disabled skills are shown greyed/non-selectable
```

Deliberately **excluded** from the snapshot projection (kept only in node-side
diagnostics, not shipped per-bro):
- `description` (full long trigger text) — replaced by the truncated/short form.
- `dependencies` — structured (`{"tools":[{"type":"mcp",…}]}`), rare, advisory;
  not needed to render the picker or activate a skill. If a future feature needs
  it, fetch on demand rather than bloating the snapshot.
- `iconSmall`/`iconLarge` — these are **node-local filesystem paths** the web UI
  cannot load. Icons are out of scope for v1 (see §4); the picker uses one
  generic glyph. Revisiting requires a node→backend icon-bytes transport.
- `scope`, `brandColor` — not needed for v1.

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
  bro's working directory as `cwds`. The response is **grouped per cwd**
  (`data: [{cwd, skills, errors}]`); the mapper flattens across groups, dedupes by
  `(name, path)`, projects each skill into the lean `ExecutorSkill` (§1), and logs
  any per-cwd `errors` to node diagnostics. The catalog spans user + system scope
  and multiple roots (`~/.codex/skills`, `~/.agents/skills`, plugin caches) —
  the node does not enumerate the filesystem itself; it trusts `skills/list`.
- `CodexExecutor` maps the response into `ExecutorCapabilities.skills`, carrying
  `enabled` through (UI greys out disabled skills — see §5).
- **Load-once-at-start freshness model (no live refresh, no new protocol).**
  Skills are loaded a single time when the executor starts up — on the first
  capability build / app-session init — and **cached on the executor**.
  `CodexExecutor` already exposes `refresh_capabilities()` (`executor.py:85`)
  which `_descriptor` calls when building the registration descriptor; the cached
  skills are included there, so the catalog rides the existing `register_node`
  capability payload to the backend with **zero protocol additions**.
  - **Consequence (intentional, documented):** the catalog is as fresh as the
    last executor (re)connect. Installing or enabling a skill is picked up by
    restarting / reconnecting that bro's computer. There is **no** `skills/changed`
    subscription and **no** `node_capabilities` message — capabilities reaching
    the backend only at `register_node` (`api/ws/executors.py:81` acks
    `node_status` without updating state) is now a fit, not a gap.
  - This is the simplest variant of the approved snapshot model: snapshot-carried
    catalog, refreshed on reconnect rather than on a live notification. A live
    `skills/changed` → push refresh is a documented future enhancement
    (see Out of scope), not part of v1.
- `acpx` / `mock` / `hosted` adapters report `skills: []` (no behavior change).
  The picker is Codex-only for now, gated on `bro.executor_node.codex` present.

## Section 3 — Selection & execution (turn activation)

**Activation primitive.** `CodexClient.turn_start` gains an optional
`skill: {name, path}`. `path` is always available from discovery (verified), so
the primary path is: append a second input item `{type:"skill", name, path}`
**and** prefix the prompt with the `$<name>` marker, so Codex injects the full
skill instructions server-side. (Defensive fallback only: if `path` were ever
missing, send marker-only `$<name>` with no skill item — relies on model
resolution. Not the expected path.)

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
  `display_name` → row title and `description` (already the short form) → row
  subtitle.
- **Icons:** skills *do* expose `iconSmall`/`iconLarge`, but as **node-local file
  paths** the web UI cannot load without a new icon-bytes transport. v1 uses the
  single generic `SKILL_DEFAULT_ICON` glyph for every row; real icons are a
  follow-up (listed in Out of scope).
- **Hint:** the prototype's per-skill `hint` maps to `ExecutorSkill.hint`
  (`interface.defaultPrompt`); when absent, fall back to a generic
  "Running with {display_name}…".
- **Desktop** (`DesktopComposerBar`, `ArtboardShell.tsx`): port the lead cluster —
  `Skill` chip ↔ selected pill, the `DTSkillMenu` popover, and the inline
  `/`-to-filter trigger (`onInputChange`, `handleKey`). Sits beside the existing
  `planChip`.
- **Mobile** (mobile composer, `ArtboardShell.tsx`): port `ThrSkillSheet` bottom
  sheet + chip/pill + `/` trigger.
- **State:** `selectedSkill` lives in composer state; cleared after send (one
  skill rides one turn). Changing the active bro clears it (catalog is per-bro).
- **Hint text:** from `ExecutorSkill.hint` (`interface.defaultPrompt`); generic
  "Running with {display_name}…" when a skill has no `defaultPrompt`.
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
- **Snapshot size:** `ExecutorSkill` is the lean projection (§1) — a real
  55-skill catalog is ~15 KB projected (vs ~40 KB raw). Still, cap an
  unexpectedly large catalog (e.g. first N, with a "+M more" affordance) to
  protect the snapshot contract across many bros.

## Section 6 — Testing

- **Fixture (captured):** `docs/protocol/fixtures/codex-skills-list-sample.json`
  is a real `skills/list` result (codex-cli 0.137.0) covering every shape variant
  (plain, interface+null icons, interface+real icons, structured `dependencies`,
  top-level `shortDescription`, grouped+errors). All adapter mapping tests replay
  against it rather than prose-inferred shapes.
- **Adapter unit:** `skills_list` request/response mapping (against the fixture);
  skills loaded once at start and cached (not re-fetched per capability build);
  `turn_start` builds the `{type:"skill"}` input item + `$name` marker when `path`
  is present, and marker-only when it is not.
- **Protocol/wire unit:** `ExecutorNodeExecutor` round-trips `skills`;
  `_descriptor` copies cached skills across into the `register_node` payload.
- **Runtime unit:** skill threads through API → `submit_executor_text_instruction`
  → instruction/command metadata; `direct_turn_starter` writes
  `outbound_metadata["skill"]`; **each** of the three turn_start sites applies the
  skill; task metadata + timeline projection render the skill pill; plan-mode +
  skill combine; **vanished-skill contract** — no metadata, no pill, notice
  present (alongside `test_session_runtime.py`).
- **Capability/snapshot:** `executor_capabilities` surfaces `skills`;
  `BroExecutorCapabilitySummary.skills` populated from the `register_node`
  payload.
- **Web unit:** picker reads catalog from snapshot (not hardcoded); `/` filter;
  selection rides on `submitExecutorTextInstruction`; pill renders from timeline
  metadata; chip hidden when empty; disabled skills greyed. Target the new test
  files, not the flaky full `App.test.tsx` suite.
- **Docs:** add a stable doc under `docs/protocol/` (skill discovery + activation
  contract) and a one-line `docs/memories.md` note, per `AGENTS.md`.

## Resolved against a live app-server (codex-cli 0.137.0, 2026-06-08)

Captured to `docs/protocol/fixtures/codex-skills-list-sample.json`:

1. **`path` IS returned** by `skills/list` for every skill → primary activation
   uses the `{type:"skill", name, path}` input item (§3). `path` is required in
   `ExecutorSkill`; marker-only is a defensive fallback only.
2. **`dependencies` is structured** (`{"tools":[{"type":"mcp",…}]}`), confirmed —
   never `list[str]`. Rare and advisory → excluded from the snapshot projection.
3. **Response is grouped per cwd** with a per-cwd `errors` array → flatten +
   dedupe by `(name, path)` (§2).
4. **Icons exist** (`interface.iconSmall/iconLarge`) but as node-local file paths
   → deferred; generic glyph in v1 (§4, Out of scope).
5. **`interface.defaultPrompt` exists** and is the natural picker hint (§4).

Remaining to confirm during implementation:
- **`cwds` for discovery** matches the cwd Codex turns actually run in for the
  bro, so the discovered catalog is the activatable one.

## Out of scope

- **Live catalog refresh** via the Codex `skills/changed` notification + a
  node→backend capability-update message. v1 loads once at executor start and
  refreshes on reconnect; live refresh is a documented future enhancement.
- Skill discovery for non-Codex executors (acpx/mock/hosted).
- Per-skill icons / custom artwork (icons exist as node-local paths; rendering
  them needs an icon-bytes transport).
- Editing, installing, or configuring skills from the UI
  (`skills/config/write`).
- Multiple skills per turn (one skill rides one turn).
- Voice-mode skill selection (composer chip is text/PTT composer first; voice
  parity is a follow-up).
```
