# Codex Skill Discovery and Activation

A Codex skill is an agent-native `SKILL.md` package the Codex app-server already
understands. Skills are **discovered per-executor** — each connected computer reports
the skills it has installed — and a chosen skill **rides one turn**, activating that
skill for that turn only. Skill and plan-mode are independent and combinable.

## Overview

Skill discovery is catalog-based: skills are loaded once at executor start via
`skills/list` and cached on the executor. The catalog rides the existing
`register_node` capability payload to the backend and is projected to the UI via
`BroExecutorCapabilitySummary.skills`. The per-bro picker in the UI reads this
snapshot catalog; a chosen skill is sent as `skill_name` on the turn request and
activates via the Codex app-server's skill input item.

## Discovery

`CodexClient.skills_list(cwds)` calls the Codex app-server `skills/list` endpoint
once at executor start. The response is **grouped per cwd**
(`{data: [{cwd, skills, errors}]}`); the adapter flattens across cwd groups, dedupes
by `(name, path)`, projects each entry into the lean `ExecutorSkill` shape (§ Lean
projection), and logs per-cwd `errors` to node diagnostics. The resulting catalog
spans user and system scope across all discovered roots (`~/.codex/skills`,
`~/.agents/skills`, plugin caches).

**Load-once / reconnect-refresh model (v1).** The catalog is cached on the executor
and included in `ExecutorCapabilities.skills` when `CodexExecutor.refresh_capabilities()`
builds the registration descriptor. This means the catalog reaches the backend as part
of the existing `register_node` payload — no new protocol message, no `skills/changed`
subscription, and no `node_capabilities` update message. The catalog is as fresh as the
last executor (re)connect; installing or enabling a skill takes effect on the next
executor reconnect.

The capability snapshot path crosses three models:

1. `ExecutorCapabilities` (`executors/core/capabilities.py`) — executor-internal; holds
   `skills: list[ExecutorSkill]`.
2. `ExecutorNodeExecutor` (`protocol/executor_node.py`) — the **wire model** carried in
   `RegisterNodeMessage.executors` and `ExecutorNodeRecord.connected_executor_capabilities`.
   Skills are copied by the hand-written field copy in `ExecutorNodeService._descriptor`
   (`executors/node/service.py`); `ExecutorNodeConnectionView` uses `model_copy(deep=True)`
   and requires no separate change.
3. `BroExecutorCapabilitySummary` (`runtime/models.py`) — the per-bro projection the UI
   reads; `skills: list[ExecutorSkill]` populated in `session.py` where the `codex`
   capability is already projected. The picker reads `bro.executor_node.codex.skills`.

`acpx`, `mock`, and `hosted` adapters always report `skills: []`; the picker is
Codex-only for now.

Live `skills/changed` refresh is a documented future enhancement, not part of v1.

Fixture: `docs/protocol/fixtures/codex-skills-list-sample.json` (real `skills/list`
result from codex-cli 0.137.0, covering every shape variant: plain, `interface` with
null icons, `interface` with real icons, structured `dependencies`, top-level
`shortDescription`, grouped with `errors`).

## Lean projection

`ExecutorSkill` carries only what is needed to render the picker and activate a skill:

| Field | Source | Notes |
|---|---|---|
| `name` | skill `name` | Codex skill identifier; used for the `$name` marker and the skill input item |
| `display_name` | `interface.displayName` → `name` | Displayed in the picker row title |
| `description` | `interface.shortDescription` → top-level `shortDescription` → `description[:160]` | Picker row subtitle; truncated |
| `hint` | `interface.defaultPrompt` | Drives the composer placeholder when a skill is selected; `None` when absent |
| `path` | skill `path` | Absolute `SKILL.md` path; always present; required for the skill input item |
| `enabled` | skill `enabled` | Disabled skills are shown greyed/non-selectable in the picker |

**Intentionally excluded** from the snapshot projection (node-side diagnostics only):
- Full `description` body — replaced by the truncated/short form above.
- `dependencies` — structured (`{"tools":[{"type":"mcp",…}]}`), rare, advisory.
- `iconSmall`/`iconLarge` — node-local filesystem paths the web UI cannot load; v1
  uses a single generic glyph. Real icon transport is a documented future enhancement.
- `scope`, `brandColor` — not needed for v1.

A real 55-skill catalog is ~40 KB raw and ~15 KB as the lean projection.

## Activation

A chosen skill rides turn metadata like `plan_mode`. The propagation chain:

```
ExecutorTextInstructionRequest.skill            (api/routes/executor_text.py)
  → session.submit_executor_text_instruction(skill=…)
  → ExecutorTextInstruction.metadata["skill"]
  → direct_turn_starter outbound_metadata["skill"]
  → StartCodexTurnCommand.metadata["skill"] / DispatchTextInstructionCommand
  → CodexExecutor (three turn_start sites): run_task / handle_text_instruction /
    start_turn_request → _turn_start_for_request
```

At each `turn_start` site, the executor:
1. Appends a `{type: "skill", name, path}` input item to the `turn/start` `input` array.
2. Prefixes the user text with the `$<name>` marker so the Codex app-server injects full
   skill instructions server-side.

If `path` is absent (defensive fallback only — not the expected path since `path` is
always returned by `skills/list`), only the `$<name>` marker is sent without a skill
input item.

Skill metadata (`{name, path, display_name}`) is persisted onto `task.metadata["skill"]`
and projected back into the timeline to render a **skill pill** on the user's turn bubble,
following the same plumbing as `_mark_timeline_message_plan_mode`
(`src/newbro/runtime/bro_detail_thread_helpers.py`).

Skill and plan-mode are independent and combinable in a single turn.

## Vanished-skill contract

The runtime validates a chosen skill against the bro's current catalog
**before writing anything** — the validate-before-write rule:

1. If the skill is present and enabled in the bro's current catalog, the turn proceeds
   normally: `skill` is written to `task.metadata`, the skill pill renders, and the
   Codex input item is appended.
2. If the skill is gone (uninstalled or disabled between pick and send): `skill` is
   **not** written to `task.metadata`, no skill pill renders, and the turn runs as a
   plain turn. An observable `skill_dropped` marker is recorded on the turn (an
   attention/notice item stating the skill is no longer available) so the UI never
   implies the skill ran.

The runtime never claims a vanished skill ran. Tested explicitly: metadata and pill
absent plus notice present on the vanished-skill path.

## UI

The per-bro skill picker reads the snapshot catalog from `bro.executor_node.codex.skills`:

- **Desktop:** a `Skill` chip in the composer lead cluster opens a `DTSkillMenu` popover;
  a selected skill shows as a pill. An inline `/`-to-filter trigger narrows the list.
- **Mobile:** a chip opens a `ThrSkillSheet` bottom sheet.
- **Display:** `display_name` as the row title, `description` as the row subtitle.
- **Hint text:** `ExecutorSkill.hint` (`interface.defaultPrompt`); generic
  "Running with {display_name}…" when absent.
- **Disabled skills:** shown greyed, non-selectable.
- **Empty / no Codex node:** the Skill chip is hidden entirely (not shown disabled).
- **State:** `selectedSkill` lives in composer state; cleared after send (one skill per
  turn). Changing the active bro clears the selection.
- **Send:** chosen skill is sent as `skill_name` on `ExecutorTextInstructionRequest`;
  the selected turn bubble renders the skill pill from `task.metadata["skill"]`.

See also [Codex wire reference](./codex-wire-reference.md).
