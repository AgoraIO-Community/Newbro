# RFC 0006: User-Defined Persona System

## Summary

Replace the current auto-assigned persona pool with a user-defined persona system where each persona is a named worker with a custom base prompt. Personas are created before task execution begins. The number of concurrent tasks is bounded by the number of personas the user has configured.

## Motivation

The current auto-assigned persona system has several problems:

1. Users have no control over persona names, personalities, or count
2. Personas are randomly assigned — no stable identity across task lifecycle
3. Cancel + recreate gives a task a new persona, confusing the user
4. No way to influence executor behavior per-persona (all executors get the same prompt)
5. Concurrency is unbounded — no natural limit on parallel tasks

The user-defined model solves all of these:

- Users name their own workers and give them personalities
- Each persona has a stable identity — "Mochi always does my coding tasks"
- Persona count = max concurrency, giving users explicit control
- Each persona's base_prompt is injected into the executor, so different personas can have different execution styles
- Users can say "let Mochi do it" for precise task routing

## Design

### Persona Model

```python
class Persona:
    persona_id: str          # "persona-mochi"
    name: str                # "Mochi"
    avatar: str              # URL to pixel-art sprite or emoji
    base_prompt: str         # injected into executor prompt
    status: "idle" | "busy"
```

### Lifecycle

```
User creates personas (via API or frontend settings)
    ↓
Session starts with N personas registered
    ↓
User says "write a red-black tree demo"
    ↓
Communication Brain picks an idle persona (or user specifies one)
    ↓
create_task with persona_id → Task.metadata.persona_id = "persona-mochi"
    ↓
Persona status → busy
    ↓
Execution Brain builds executor prompt:
    system_prompt = persona.base_prompt + task.goal + task.constraints
    ↓
Executor runs with persona-flavored prompt
    ↓
Task completes/fails/cancelled
    ↓
Persona status → idle
    ↓
Persona is available for next task
```

### Storage

Personas live on the blackboard alongside tasks and sessions:

```
BlackboardStore:
    put_persona(persona) / get_persona(id) / list_personas()
```

This keeps them in the same snapshot pipeline — frontend gets personas in SessionSnapshot, same WebSocket channel.

### Task Assignment

When `create_task` is called:

1. If user specified a persona name → resolve to persona_id, assign
2. If no persona specified → Communication Brain MUST ask the user which persona to assign. Do NOT auto-pick. Example: "Who should handle this? Mochi and Pixel are both free."
3. If all personas are busy → reject with persona-specific context: "Mochi and Pixel are both busy right now. Want one of them to drop what they're doing?"
4. If only one persona is idle → Communication Brain may suggest: "Only Mochi is free. Want him on this?"

The same rule applies to `update_task` and `add_constraint` — if the user mentions a task without specifying which persona it belongs to, and the target is ambiguous, ask rather than guess.

### Executor Prompt Injection

The key behavioral change: each persona's `base_prompt` is prepended to the executor's task prompt.

Currently in `reconcile.py`, the executor gets:
```
executor.run_task(run, task, executor_session)
```

The executor's `_build_prompt(task)` builds the prompt from `task.title`, `task.goal`, etc.

With personas, the prompt becomes:
```
[persona.base_prompt]\n\n[task prompt as before]
```

This means:
- A persona with base_prompt "You are a meticulous code reviewer who writes extensive tests" will produce different executor output than one with "You are a fast prototyper who prioritizes shipping quickly"
- The user controls execution style through persona configuration, not through per-task instructions

### Communication Brain Integration

The Communication Brain sees personas in the runtime context:

```json
{
  "personas": [
    {"persona_id": "persona-mochi", "name": "Mochi", "status": "busy"},
    {"persona_id": "persona-pixel", "name": "Pixel", "status": "idle"}
  ]
}
```

Prompt rules:
- Use persona names when referring to tasks ("Mochi is working on the red-black tree demo")
- When user says "let Mochi do it" → assign to that persona
- When user says "what is Mochi doing" → query that persona's current task
- First-time introduction: "Let me bring in a new bro: Mochi. He will handle this for us."
- When all personas are busy: "Mochi and Pixel are both busy right now. Want one of them to drop what they're doing?"
- When user requests a task without specifying a persona: ALWAYS ask which persona should handle it. Do NOT silently auto-assign.
- When user mentions a task ambiguously during update/constraint: ask which persona's task they mean.

### Concurrency Control

Max concurrent tasks = number of personas with status != "busy".

This is enforced at `create_task` time, not in the reconcile loop. The reconcile loop continues to process all runnable tasks — the constraint is upstream.

### API Surface

```
POST   /sessions/{id}/personas          — create a persona
GET    /sessions/{id}/personas          — list personas
PATCH  /sessions/{id}/personas/{pid}    — update name/avatar/base_prompt
DELETE /sessions/{id}/personas/{pid}    — remove (only if idle)
```

Personas can also be created via the Communication Brain — user says "create a worker named Mochi who is good at coding" and the Communication Brain calls a `create_persona` tool.

### Frontend

- Settings panel: create/edit/delete personas with name, avatar picker (pixel art), and base_prompt textarea
- Task cards: show persona avatar + name instead of task_id
- Persona status indicators: idle/busy with current task title
- Persona gallery: row of pixel-art avatars at the top of the blackboard view

## Open Questions

1. **Persona persistence across sessions:** YES — store persona configs in `~/.synapse/personas.yaml`. Auto-load on session creation. Users should not have to recreate personas every time.

2. **Persona-executor binding:** DEFERRED to v2. First version uses the session's default executor for all personas. Future version allows per-persona executor_type binding for true multi-executor parallel execution.

3. **Communication Brain `create_persona` tool:** DEFERRED. Good idea for future — user says "give me a new worker named X who is good at Y" and the Communication Brain creates it. For now, personas are managed via API/frontend/config file only.

4. **Persona limit:** No hard cap. Users can create as many personas as they want. Resource management is the user's responsibility.

5. **What happens when a persona's task is cancelled?** Persona goes idle immediately and is available for new tasks. If the user says "continue" on a cancelled task, it goes back to the same persona if idle, otherwise any idle persona.

6. **Base prompt language:** User's choice. The base_prompt is passed through as-is to the executor. Users who want better executor results should write it in the language the executor works best with.

## V1 Scope

Included:
- Persona model with name, avatar, base_prompt
- Persistence in `~/.synapse/personas.yaml`, auto-loaded on session start
- Blackboard storage for runtime persona status
- Task assignment: user-specified or auto-pick idle persona
- Busy check: reject task creation when all personas are busy
- Executor prompt injection: persona.base_prompt prepended to task prompt
- Communication Brain persona-aware prompts
- SessionSnapshot includes persona list
- REST API for CRUD
- Frontend persona management + task card persona display

Not included (v2):
- Per-persona executor type binding
- Communication Brain `create_persona` tool
- Persona concurrency cap

## Migration from Current System

1. Delete `persona_pool.py` and remove all `PersonaAssigner` references
2. Add `Persona` model to protocol (replaces the old auto-assign model)
3. Add persona storage to blackboard + persistence to `~/.synapse/personas.yaml`
4. Add persona fields to `SessionSnapshot`
5. Modify `create_task` tool: accept `persona_id` or `persona_name`, require explicit assignment (ask user if not specified)
6. Modify reconcile loop to inject `persona.base_prompt` into executor prompt
7. Update Communication Brain prompts: use persona names, ask before assigning, report busy status with names
8. Add persona REST API endpoints
9. Add frontend persona management UI

## Relationship to Existing Architecture

This design stays within the existing dual-brain architecture:

- Communication Brain owns persona selection and user-facing persona references
- Execution Brain owns prompt injection and task-persona binding during execution
- Blackboard stores persona state as a first-class object
- Personas do not replace executors — they are a layer above, controlling how executors are prompted
