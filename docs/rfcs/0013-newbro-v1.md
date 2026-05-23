# PRD / HLD: Quiet Communication Layer for Long-Running Agents

## 1. One-Line Summary

Build a quiet, real-time communication layer that lets a user naturally supervise long-running agents such as Hermes through voice or text, while preventing wrong dispatches through structured task grounding, confirmation gates, and a shared blackboard.

---

## 2. Product Thesis

The product is not “voice chat with Hermes.”

It is a **real-time operator layer for supervising long-running AI workers**.

The user should feel like they are communicating with a calm dispatcher that can:

* understand intent from live speech or text,
* convert messy instructions into structured task drafts,
* confirm before sending work to execution agents,
* route tasks to the correct worker,
* monitor long-running progress,
* stay quiet unless the user needs to decide or something important happens,
* allow the user to interrupt, correct, stop, or ask for status at any time.

The execution agent, such as Hermes, should not be directly exposed as the conversational interface. Hermes is the worker. The communication brain is the operator.

---

## 3. Background and Motivation

Current voice agents and agent dispatch systems tend to fail in two ways:

1. **Wrong dispatch**

   * The system sends the wrong task to Hermes.
   * Hermes wastes time, pollutes context, or touches the wrong files.
   * The user loses trust.

2. **Noisy communication**

   * The communication layer narrates too much.
   * It acknowledges every small update.
   * It speaks raw agent progress events.
   * Long-running work becomes distracting instead of helpful.

The desired system should solve both problems:

* Dispatch should be **structured, staged, validated, and confirmed**.
* Communication should be **silence-first, short, and decision-oriented**.

---

## 4. Inspiration from Interaction Model Research

The relevant research insight is not that we need a custom foundation model immediately. The useful lesson is architectural:

* Separate the **real-time interaction layer** from the **long-running execution layer**.
* Keep a lightweight interaction system continuously available to the user.
* Let slower background agents do heavy work asynchronously.
* Treat timing, interruptions, pauses, and corrections as part of meaning.
* Do not dump background work into the conversation. Surface it only when useful.

Mapped to this product:

| Research Concept                           | Product Equivalent                                  |
| ------------------------------------------ | --------------------------------------------------- |
| Interaction model                          | Communication brain                                 |
| Background model                           | Hermes / Codex / OpenClaw / browser agent           |
| Shared context                             | Blackboard                                          |
| Micro-turn awareness                       | STT events + state machine + interaction classifier |
| Interruption-aware UX                      | Stop / pause / correct / replace task flows         |
| Background results woven into conversation | Quiet status summarizer                             |

---

## 5. Goals

### 5.1 Product Goals

1. Let users create tasks for long-running agents through natural voice or text.
2. Prevent wrong dispatches by staging and validating tasks before execution.
3. Keep the communication brain quiet by default.
4. Support corrections before and after dispatch.
5. Support long-running agent progress without noisy narration.
6. Support multilingual and code-switched input.
7. Provide a clean foundation for multiple execution agents.

### 5.2 Technical Goals

1. Build an event-driven communication runtime.
2. Maintain structured session state and task state.
3. Introduce a staged dispatch pipeline:

   * user utterance,
   * draft,
   * dispatch plan,
   * dispatch gate,
   * execution task.
4. Use a deterministic gate to decide whether execution can start.
5. Use a shared blackboard for task state, progress, artifacts, and summaries.
6. Support adapter-based integration with Hermes and other agents.
7. Integrate with Agora Conversational AI as the real-time speech shell.

---

## 6. Non-Goals

1. Do not build a fully autonomous agent that acts without grounding.
2. Do not expose Hermes directly as the real-time conversational brain.
3. Do not dispatch raw user speech directly to execution agents.
4. Do not narrate every progress event.
5. Do not require a custom low-level foundation model in v0.
6. Do not support arbitrary multi-agent collaboration in v0.
7. Do not allow destructive or external side-effect actions without explicit approval.

---

## 7. Target Users

### 7.1 Primary User

A power user supervising AI workers for development, research, design, or operations.

Examples:

* DevX owner directing Hermes to inspect prototypes, repos, docs, console IA, or integration issues.
* Engineer using voice to assign debugging, code investigation, or proposal-generation tasks.
* Product lead using agents to review UI/UX, summarize findings, or generate artifacts.

### 7.2 Secondary User

A user who wants a natural voice interface to delegate work, but does not want the agent to act prematurely.

---

## 8. Core User Experience

### 8.1 Ideal Interaction

User:

> 让 Hermes 看一下 new console 的 settings page，感觉太挤了，参考一下 Linear 和 ElevenLabs。

Communication brain:

> 已草拟给 Hermes。发送吗？

UI draft card:

```text
To: Hermes
Mode: Read-only first

Task:
Review the new console Settings page, identify why it feels too dense, and propose simplification ideas.

References:
- Linear
- ElevenLabs

Output:
Short proposal in Chinese

Constraints:
- Do not modify code yet
- Ask before making changes
```

User:

> 先不要改代码，只要 proposal。

Communication brain:

> silent

UI updates silently:

```text
Mode: Proposal only
Do not modify code
```

User:

> Send.

Communication brain:

> Sent to Hermes.

Hermes works in the background. Progress is written to the blackboard and UI, but not spoken unless needed.

User:

> Hermes 现在在干嘛？

Communication brain:

> Hermes 找到一个主要问题：这个页面把 setup、capability discovery 和 account settings 混在一起了。它现在在整理 proposal。

Hermes completes.

Communication brain:

> Hermes 完成了。有一份 proposal 可以看。

---

## 9. Product Principles

### 9.1 Quiet by Default

The communication brain should be present, not performative.

Default behavior:

```text
Do not speak unless there is a reason.
```

Speak only when:

* user confirmation is required,
* missing context blocks dispatch,
* Hermes is blocked,
* Hermes completes,
* the user asks for status,
* permission is required,
* there is a high-risk or urgent event.

### 9.2 Dispatch Is Never Raw

Never dispatch directly from raw user speech.

Required flow:

```text
User utterance → Draft → Dispatch Plan → Dispatch Gate → Agent Task
```

### 9.3 Hermes Is Read-Only First

Default execution mode:

```text
Inspect and propose. Do not modify.
```

Escalation requires user confirmation:

```text
investigate → propose → modify → submit
```

### 9.4 State Determines Meaning

The same phrase can mean different things depending on state.

Example:

| User Says                 | State          | Meaning                           |
| ------------------------- | -------------- | --------------------------------- |
| “Wait”                    | Drafting       | pause / correction                |
| “Wait”                    | AI speaking    | interrupt assistant               |
| “Wait”                    | Hermes running | stop or pause task                |
| “Actually make it Friday” | Drafting       | update draft                      |
| “Actually make it Friday” | Task running   | add follow-up or stop-and-replace |

### 9.5 UI Carries State, Voice Carries Decisions

Visual UI should show:

* transcript,
* draft card,
* staged dispatch plan,
* running task state,
* progress summary,
* artifacts.

Voice should be used for:

* short confirmations,
* clarifying questions,
* blocked/done notifications,
* direct status answers.

---

## 10. Key Concepts

### 10.1 Communication Brain

The communication brain is the real-time operator layer.

Responsibilities:

* classify user utterances,
* maintain live draft state,
* create structured task specs,
* stage dispatch plans,
* ask for confirmation or clarification,
* route work to agents,
* monitor task state,
* summarize progress,
* respond to task control commands,
* stay quiet unless necessary.

It should not:

* execute long-running tasks itself,
* directly mutate repos/files,
* narrate every event,
* send raw speech to Hermes.

### 10.2 Execution Agent

Hermes is a long-running worker.

Responsibilities:

* perform investigation,
* run tools,
* inspect repos/docs/prototypes,
* generate artifacts,
* report progress/events,
* stop when blocked or when permission is needed.

Hermes should receive structured task packets, not raw conversation.

### 10.3 Blackboard

The blackboard is shared task memory.

It stores:

* session state,
* draft state,
* staged dispatch plans,
* task records,
* agent events,
* summaries,
* artifacts,
* user corrections,
* permission decisions.

### 10.4 Dispatch Plan

A dispatch plan is a structured, staged object describing what should be sent to an execution agent.

It exists before the actual task starts.

### 10.5 Dispatch Gate

A deterministic validator that decides whether a dispatch plan can become a running task.

The model may propose a plan. The gate decides.

---

## 11. Functional Requirements

### 11.1 Input Handling

The system shall support:

* voice input through Agora Conversational AI,
* text input through UI or API,
* live STT partial transcripts,
* final transcript segments,
* multilingual and code-switched input,
* user interruptions while the assistant is speaking,
* explicit commands such as “send,” “stop,” “cancel,” “status,” and “actually.”

### 11.2 Interaction Classification

The system shall classify each meaningful user utterance into one of the following interaction types:

```text
COMMUNICATION
DELEGATION
DRAFT_CORRECTION
TASK_CONTROL
STATUS_QUERY
CONFIRMATION
CLARIFICATION_RESPONSE
UNCERTAIN
```

Only `DELEGATION` may enter the task formulation and routing pipeline.

### 11.3 Draft Management

The system shall maintain a live draft before dispatch.

Drafts shall support:

* create from user utterance,
* update from correction,
* update from added constraints,
* cancel,
* stage for dispatch,
* freeze into task after confirmation.

Draft updates should be visual-first and silent by default.

### 11.4 Task Formulation

The system shall convert delegation intent into a structured task spec.

Required fields:

```json
{
  "title": "string",
  "goal": "string",
  "target_agent": "string",
  "mode": "read_only_first | proposal_only | modify_allowed | submit_allowed",
  "expected_output": "string",
  "constraints": ["string"],
  "success_criteria": ["string"],
  "stop_conditions": ["string"],
  "context": {},
  "input_language": "string",
  "output_language": "string"
}
```

### 11.5 Dispatch Gate

The system shall prevent dispatch unless all required conditions pass.

Gate conditions:

* confidence above threshold,
* task has clear goal,
* task has clear target/context,
* agent is allowed for task type,
* missing context is empty,
* risk level is acceptable,
* user confirmation exists if required,
* task mode is safe by default.

Gate outcomes:

```text
ASK_CLARIFICATION
ASK_CONFIRMATION
DISPATCH
REJECT
```

### 11.6 Agent Routing

The system shall route tasks using an explicit routing table.

Example:

```json
{
  "repo_investigation": ["hermes", "codex"],
  "code_modification": ["codex", "hermes"],
  "ux_review": ["hermes"],
  "web_research": ["browser_agent"],
  "status_query": ["communication_brain"],
  "draft_correction": ["communication_brain"],
  "task_control": ["task_manager"]
}
```

### 11.7 Hermes Adapter

The system shall integrate Hermes through an adapter interface.

Required methods:

```python
class AgentAdapter:
    def start_task(self, task: Task) -> AgentRun: ...
    def stop_task(self, task_id: str) -> None: ...
    def send_message(self, task_id: str, message: str) -> None: ...
    def get_events(self, task_id: str) -> list[AgentEvent]: ...
    def get_latest_summary(self, task_id: str) -> str: ...
```

### 11.8 Progress Handling

Hermes shall write progress events to the blackboard.

The communication brain shall not speak every event.

Events shall include delivery policy:

```json
{
  "type": "agent.progress",
  "importance": "low | medium | high | urgent",
  "delivery": "silent | silent_ui | badge | short_voice | voice_interrupt"
}
```

Default progress delivery:

```text
silent_ui
```

### 11.9 Status Query

When the user asks for status, the communication brain shall summarize the latest relevant blackboard state.

Example:

> Hermes found that the page mixes setup, capability discovery, and account settings. It is now drafting a simpler IA proposal.

### 11.10 Blocked State

When Hermes is blocked, the system shall notify the user with a short message.

Examples:

* “Hermes needs the prototype URL.”
* “Hermes needs permission before editing files.”
* “Hermes cannot continue without repo access.”

### 11.11 Task Correction After Dispatch

For running tasks, corrections shall not silently mutate the task.

Supported actions:

1. Add follow-up instruction to the running task.
2. Stop current task and create a replacement task.
3. Create a child task.
4. Ask user to choose if risk is high.

Example:

User:

> Actually, don’t focus settings page. Focus Home page.

Communication brain:

> This changes the task direction. Stop the current Hermes task and create a new Home page review task?

### 11.12 Multilingual Support

The system shall support multilingual and code-switched input.

Each event should include:

```json
{
  "input_language": "zh-CN",
  "output_language": "zh-CN",
  "code_switched": true,
  "raw_transcript": "让 Hermes 看一下 settings page 为什么太挤",
  "normalized_task_language": "en-US"
}
```

Policy:

* user-facing responses should match the user’s language,
* product names should not be over-translated,
* Hermes task specs may be normalized to English,
* final artifacts should follow the user’s requested language.

---

## 12. Non-Functional Requirements

### 12.1 Latency

* 200ms loop: update interaction state and reflex signals.
* 1s loop: classify interaction event from partial transcript and state.
* Draft rewrite: target 1–2 seconds after stable transcript or turn boundary.
* Dispatch confirmation: immediate after task spec is valid.

### 12.2 Reliability

* No task should be dispatched without a valid task spec.
* No medium/high-risk task should start without confirmation.
* Running tasks should be stoppable.
* Agent events should be persisted.
* Task state should be recoverable after process restart.

### 12.3 Safety

* Default task mode is read-only first.
* Code modification requires explicit permission.
* External side effects require explicit permission.
* Credentials and secrets should never be requested through unstructured voice prompts.
* Execution agents should stop when encountering permission boundaries.

### 12.4 Observability

The system should log:

* raw transcript,
* normalized intent,
* classifier output,
* task spec,
* dispatch gate result,
* user confirmation,
* agent events,
* summaries,
* spoken response decision.

---

## 13. High-Level Architecture

```text
User
  ↓ voice/text
Agora Conversational AI / Client UI
  ↓ transcript events / user messages
Communication Runtime
  ├─ Session State Manager
  ├─ Interaction Classifier
  ├─ Draft Manager
  ├─ Task Formulator
  ├─ Task Linter
  ├─ Agent Router
  ├─ Dispatch Gate
  ├─ Speech Policy Engine
  ├─ Status Summarizer
  └─ Agent Adapter Manager
        ↓
Blackboard / State Store
  ├─ sessions
  ├─ drafts
  ├─ dispatch_plans
  ├─ tasks
  ├─ agent_events
  ├─ summaries
  └─ artifacts
        ↓
Execution Agents
  ├─ Hermes
  ├─ Codex
  ├─ Browser Agent
  └─ API Workers
```

---

## 14. Component Design

### 14.1 Agora Conversational AI Layer

Purpose:

* handle real-time audio,
* provide ASR transcript events,
* speak communication brain responses through TTS,
* support interruption handling,
* manage the voice-agent session lifecycle through the Agora Python Agent Server SDK.

Recommended integration:

```text
Agora Python Agent Server SDK
  ├─ RTC / Conversational AI session lifecycle
  ├─ ASR transcript events
  ├─ TTS response streaming
  ├─ interruption / turn events
  └─ agent callbacks
        ↓
Communication Runtime
  ├─ interaction classifier
  ├─ draft manager
  ├─ dispatch gate
  ├─ speech policy engine
  └─ Hermes adapter
```

The implementation should use the **Agora Python Agent Server SDK** as the primary server-side integration layer. The communication runtime should be embedded behind the SDK callback/event handlers rather than implemented first as a generic OpenAI-compatible LLM proxy.

The OpenAI-compatible endpoint can remain as an optional compatibility mode, but the preferred implementation path is:

```text
Agora Python Agent Server SDK
→ receive transcript / turn / interruption events
→ call communication runtime
→ stream short response text back through Agora TTS
→ keep Hermes execution asynchronous through the blackboard
```

### 14.2 Communication Runtime

Main API responsibilities:

* receive user messages/transcripts,
* load session state,
* classify interaction,
* update drafts or tasks,
* decide whether to speak,
* stream short response back to Agora/client.

Pseudo-code:

```python
def on_user_message(text, session_id):
    state = load_session_state(session_id)

    interaction = classify_interaction(text, state)

    if interaction.kind != "DELEGATION":
        return handle_non_delegation(interaction, state)

    task_spec = formulate_task(text, state)
    lint = lint_task(task_spec)

    if not lint.valid:
        return ask(lint.clarifying_question)

    route = route_agent(task_spec)
    plan = create_dispatch_plan(task_spec, route)
    gate = dispatch_gate(plan, state)

    if gate.action == "ASK_CONFIRMATION":
        state.staged_task = plan
        save_state(state)
        return say(f"Drafted for {route.agent}. Send?")

    if gate.action == "DISPATCH":
        task = dispatch_to_agent(plan)
        save_state(state)
        return say(f"Sent to {route.agent}.")

    return ask(gate.question)
```

### 14.3 Interaction Classifier

Input:

```json
{
  "text": "Actually focus Home page instead",
  "session_state": "TASK_RUNNING",
  "ai_speaking": false,
  "task_running": true,
  "draft_exists": false,
  "active_task_summary": "Review Settings page density"
}
```

Output:

```json
{
  "kind": "TASK_CONTROL",
  "subtype": "DIRECTION_CHANGE",
  "confidence": 0.88
}
```

Recommended implementation:

* rules for high-confidence commands,
* local small classifier for common interaction labels,
* stronger LLM fallback for ambiguous multilingual cases.

### 14.4 Draft Manager

Responsibilities:

* create draft,
* update draft silently,
* cancel draft,
* stage draft as dispatch plan,
* freeze draft into task.

Draft state:

```json
{
  "draft_id": "draft_123",
  "session_id": "session_abc",
  "target_agent": "hermes",
  "title": "Review console settings page density",
  "goal": "Review the new console Settings page and propose simplification ideas.",
  "mode": "proposal_only",
  "constraints": ["Do not modify code"],
  "status": "staged",
  "needs_confirmation": true
}
```

### 14.5 Task Linter

Checks:

* clear goal,
* clear target,
* expected output,
* mode specified,
* risk level,
* missing context,
* agent compatibility,
* stop conditions.

Output:

```json
{
  "valid": false,
  "problems": [
    "No target repository or prototype specified"
  ],
  "clarifying_question": "Which repo or prototype should Hermes inspect?"
}
```

### 14.6 Agent Router

Routes structured task specs to eligible agents.

Example:

```python
def route_agent(task_spec):
    allowed = ROUTING_TABLE[task_spec.task_type]
    if task_spec.target_agent in allowed:
        return task_spec.target_agent
    return best_agent_for(task_spec)
```

### 14.7 Dispatch Gate

Deterministic gate.

Pseudo-code:

```python
def can_dispatch(plan):
    if plan.confidence < 0.85:
        return False, "low_confidence"

    if plan.missing_context:
        return False, "missing_context"

    if plan.risk_level in ["medium", "high"]:
        return False, "needs_confirmation"

    if plan.target_agent not in allowed_agents_for_intent(plan.intent):
        return False, "agent_mismatch"

    if not plan.user_confirmed:
        return False, "needs_confirmation"

    return True, "ok"
```

### 14.8 Speech Policy Engine

Determines whether the communication brain should speak.

Default:

```text
silent
```

Pseudo-code:

```python
def should_speak(event, state):
    if event.requires_user_decision:
        return True

    if event.type == "task.blocked":
        return True

    if event.type == "task.completed":
        return True

    if event.type == "user.status_query":
        return True

    if event.type == "risk.permission_required":
        return True

    if event.importance == "urgent":
        return True

    return False
```

Response style must be short:

```text
“Drafted for Hermes. Send?”
“Which repo?”
“Hermes is blocked.”
“Hermes finished.”
“Stopped. New task sent.”
```

### 14.9 Status Summarizer

Reads recent agent events and latest summary from blackboard.

Inputs:

* raw Hermes events,
* task state,
* latest artifact metadata,
* user’s question.

Output:

* short spoken summary,
* longer UI summary if needed.

### 14.10 Hermes Adapter

Converts task specs into Hermes sessions.

Responsibilities:

* start Hermes run,
* pass structured task packet,
* capture logs/progress,
* emit normalized agent events,
* detect blocked state,
* collect artifacts,
* stop or pause run.

Normalized event examples:

```json
{
  "type": "agent.progress",
  "task_id": "task_123",
  "agent_id": "hermes",
  "message": "Compared current layout against Linear console.",
  "importance": "low",
  "delivery": "silent_ui"
}
```

```json
{
  "type": "agent.blocked",
  "task_id": "task_123",
  "agent_id": "hermes",
  "reason": "Need latest prototype URL",
  "importance": "high",
  "delivery": "short_voice"
}
```

---

## 15. Data Model

### 15.1 Session

```json
{
  "session_id": "session_abc",
  "user_id": "user_123",
  "input_language": "zh-CN",
  "output_language": "zh-CN",
  "state": "DRAFTING | WAITING_CONFIRMATION | TASK_RUNNING | TASK_BLOCKED | TASK_COMPLETE",
  "current_draft_id": "draft_123",
  "active_task_id": "task_456",
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

### 15.2 Dispatch Plan

```json
{
  "plan_id": "plan_123",
  "session_id": "session_abc",
  "intent": "ux_review",
  "target_agent": "hermes",
  "task_title": "Review console settings page density",
  "task_goal": "Review the new console Settings page, identify why it feels dense, and propose simplification ideas.",
  "required_context": ["prototype_url"],
  "missing_context": [],
  "mode": "proposal_only",
  "risk_level": "low",
  "confidence": 0.91,
  "requires_user_confirmation": true,
  "user_confirmed": false,
  "output_language": "zh-CN"
}
```

### 15.3 Task

```json
{
  "task_id": "task_456",
  "plan_id": "plan_123",
  "title": "Review console settings page density",
  "goal": "Review the new console Settings page, identify why it feels dense, and propose simplification ideas.",
  "assigned_agent": "hermes",
  "mode": "proposal_only",
  "status": "queued | running | blocked | completed | stopped | failed",
  "constraints": ["Do not modify code"],
  "success_criteria": [
    "Identify causes of perceived density",
    "Compare with Linear and ElevenLabs",
    "Produce a short Chinese proposal"
  ],
  "stop_conditions": [
    "Need credentials",
    "Need permission to modify code",
    "Need unavailable prototype URL"
  ],
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

### 15.4 Agent Event

```json
{
  "event_id": "event_789",
  "task_id": "task_456",
  "agent_id": "hermes",
  "type": "agent.progress | agent.blocked | artifact.ready | task.completed | task.failed",
  "message": "Found likely density issue: mixed setup, capability discovery, and account settings.",
  "importance": "medium",
  "delivery": "silent_ui",
  "created_at": "timestamp"
}
```

---

## 16. State Machine

### 16.1 Session States

```text
IDLE
DRAFTING
WAITING_FOR_CONFIRMATION
TASK_RUNNING
TASK_BLOCKED
TASK_COMPLETE
USER_REVIEWING_ARTIFACT
```

### 16.2 State Transitions

```text
IDLE
  → DRAFTING                    user delegates work

DRAFTING
  → WAITING_FOR_CONFIRMATION     task spec valid
  → IDLE                         user cancels

WAITING_FOR_CONFIRMATION
  → TASK_RUNNING                 user confirms send
  → DRAFTING                     user corrects draft
  → IDLE                         user cancels

TASK_RUNNING
  → TASK_BLOCKED                 agent blocked
  → TASK_COMPLETE                agent completes
  → IDLE                         user stops task
  → WAITING_FOR_CONFIRMATION     user requests major direction change

TASK_BLOCKED
  → TASK_RUNNING                 user provides missing context
  → IDLE                         user stops task

TASK_COMPLETE
  → USER_REVIEWING_ARTIFACT      user opens artifact
  → IDLE                         user dismisses
```

---

## 17. API Design

### 17.1 User Message API

```http
POST /sessions/{session_id}/messages
```

Request:

```json
{
  "type": "text | stt_partial | stt_final",
  "text": "让 Hermes 看一下 settings page 为什么太挤",
  "language": "zh-CN",
  "timestamp_ms": 18420
}
```

Response:

```json
{
  "spoken_response": "已草拟给 Hermes。发送吗？",
  "should_speak": true,
  "ui_updates": [
    {
      "type": "draft_card.updated",
      "draft_id": "draft_123"
    }
  ]
}
```

### 17.2 Dispatch Confirmation API

```http
POST /dispatch-plans/{plan_id}/confirm
```

Response:

```json
{
  "task_id": "task_456",
  "status": "queued",
  "spoken_response": "Sent to Hermes."
}
```

### 17.3 Task Status API

```http
GET /tasks/{task_id}/status
```

Response:

```json
{
  "task_id": "task_456",
  "status": "running",
  "latest_summary": "Hermes found that the page mixes setup, capability discovery, and account settings.",
  "artifacts": []
}
```

### 17.4 Task Stop API

```http
POST /tasks/{task_id}/stop
```

Response:

```json
{
  "task_id": "task_456",
  "status": "stopped",
  "spoken_response": "Stopped."
}
```

### 17.5 Agent Event Ingest API

```http
POST /tasks/{task_id}/events
```

Request:

```json
{
  "agent_id": "hermes",
  "type": "agent.progress",
  "message": "Compared settings page against Linear.",
  "importance": "low",
  "delivery": "silent_ui"
}
```

---

## 18. Agora Python Agent Server SDK Integration

The preferred Agora implementation shall use the **Agora Python Agent Server SDK**.

The communication runtime should be implemented as the server-side agent logic that receives Agora session events and produces short, policy-controlled responses.

### 18.1 Runtime Placement

```text
Client / device
  ↓ RTC audio
Agora Conversational AI
  ↓
Agora Python Agent Server SDK
  ↓ transcript / turn / interruption callbacks
Communication Runtime
  ├─ session state manager
  ├─ interaction classifier
  ├─ draft manager
  ├─ dispatch gate
  ├─ speech policy engine
  └─ Hermes adapter
  ↓ short response or silence decision
Agora Python Agent Server SDK
  ↓ TTS / response streaming
Client / device
```

### 18.2 SDK Event Handling

The implementation should map SDK callbacks/events into internal communication events:

```text
ASR partial transcript      → stt.partial
ASR final transcript        → stt.final
user speech start           → user.speech_started
user speech end             → user.speech_ended
assistant speech start      → assistant.speech_started
assistant speech end        → assistant.speech_ended
user interruption/barge-in  → interaction.interrupted
session start               → session.started
session end                 → session.ended
```

### 18.3 Communication Runtime Contract

The SDK handler should call one internal method:

```python
def handle_agora_event(event: AgoraAgentEvent, session_id: str) -> RuntimeDecision:
    ...
```

`RuntimeDecision` should include:

```json
{
  "should_speak": true,
  "response_text": "Drafted for Hermes. Send?",
  "ui_updates": [],
  "state_updates": [],
  "async_actions": []
}
```

If the speech policy engine decides silence is preferred:

```json
{
  "should_speak": false,
  "response_text": "",
  "ui_updates": [
    {"type": "draft_card.updated"}
  ]
}
```

### 18.4 Silent Behavior

The SDK integration must support a silence-first behavior.

For events such as draft micro-updates or low-importance Hermes progress:

```text
Do not stream TTS response.
Update UI / blackboard only.
```

For events requiring a spoken response:

```text
Stream only a short response through Agora TTS.
```

Examples:

```text
“Drafted for Hermes. Send?”
“Which repo?”
“Hermes needs the prototype URL.”
“Hermes finished.”
```

### 18.5 Optional Compatibility Endpoint

An OpenAI-compatible `/v1/chat/completions` endpoint may be provided as a compatibility layer for testing or non-SDK deployments.

However, this is not the primary implementation path.

Preferred:

```text
Agora Python Agent Server SDK callbacks → Communication Runtime
```

Optional:

```text
OpenAI-compatible LLM endpoint → Communication Runtime
```

---

## 19. Model Strategy

### 19.1 200ms Loop

No LLM.

Use:

* STT event freshness,
* VAD if available,
* AI speaking state,
* user speaking state,
* barge-in detection,
* UI state update.

### 19.2 1s Interaction Classifier

Use:

* rules first,
* **Gemma 4 E4B local classifier as the preferred optional local model**,
* hosted LLM fallback for uncertainty.

Gemma 4 should be used only for lightweight interaction classification:

```text
partial transcript + session state → interaction label + confidence
```

It should not be used as:

* the 200ms reflex loop,
* the deterministic dispatch gate,
* the main communication brain,
* the Hermes execution worker,
* the final authority on whether a task can be dispatched.

Recommended local setup:

```text
Model: Gemma 4 E4B, 4-bit quantized
Runtime: local model server on the M4 MacBook Pro
Usage: 1s interaction classifier only
Fallback: hosted stronger LLM when confidence is low or input is multilingual/ambiguous
```

Labels:

```text
COMMUNICATION
DELEGATION
DRAFT_CORRECTION
TASK_CONTROL
STATUS_QUERY
CONFIRMATION
CLARIFICATION_RESPONSE
UNCERTAIN
```

Classifier output:

```json
{
  "label": "DELEGATION",
  "confidence": 0.91,
  "subtype": "ux_review",
  "reason": "User is asking Hermes to inspect a page and produce a proposal."
}
```

Dispatch safety rule:

```text
Gemma 4 may classify intent, but it must never bypass the task linter or dispatch gate.
```

### 19.3 Draft Rewrite / Task Normalization

Use a stronger LLM when transcript stabilizes or user finishes an utterance.

Input:

* raw transcript,
* previous draft,
* session state,
* active task state,
* output language.

Output:

* clean draft,
* task spec,
* missing context,
* confidence.

### 19.4 Agent Execution

Hermes or other long-running agents perform actual work.

---

## 20. Multilingual Design

### 20.1 Language Policy

* Detect input language per utterance.
* Maintain session output language.
* Preserve product names such as Hermes, Codex, Console, Settings, PR, repo.
* Normalize execution task specs to English if useful.
* Produce user-facing responses in the user’s language.

### 20.2 Code-Switching Example

User:

> 帮我让 Hermes review 一下 console settings，感觉太挤了。

Normalized task:

```json
{
  "title": "Review console settings page density",
  "goal": "Review the console Settings page and propose simplification ideas.",
  "output_language": "zh-CN"
}
```

Response:

> 已草拟给 Hermes。发送吗？

---

## 21. UI Requirements

### 21.1 Required UI Elements

1. Live transcript area.
2. Draft card.
3. Dispatch plan preview.
4. Active task card.
5. Agent status timeline.
6. Latest summary.
7. Artifact list.
8. Stop / Send / Cancel controls.

### 21.2 Draft Card

Should show:

* target agent,
* mode,
* task summary,
* expected output,
* constraints,
* missing context,
* confirmation state.

### 21.3 Active Task Card

Should show:

* status,
* assigned agent,
* latest summary,
* elapsed time,
* blockers,
* artifacts,
* stop button.

---

## 22. Voice UX Rules

### 22.1 Allowed Spoken Forms

Confirmation:

> Drafted for Hermes. Send?

Clarification:

> Which repo?

Blocked:

> Hermes needs the prototype URL.

Done:

> Hermes finished. Review the proposal?

Status:

> Hermes found the main issue and is drafting a proposal.

### 22.2 Disallowed Spoken Forms

Avoid:

* long explanations,
* raw logs,
* repeated acknowledgements,
* narrating every action,
* “I’m now doing X” unless useful,
* reading full artifacts aloud by default.

---

## 23. Risk and Mitigation

### 23.1 Wrong Dispatch

Risk:

* Hermes receives the wrong task.

Mitigation:

* staged dispatch plan,
* task linter,
* deterministic gate,
* confirmation requirement,
* read-only first mode.

### 23.2 Noisy Communication

Risk:

* user is interrupted by unnecessary updates.

Mitigation:

* silence-first policy,
* speech budget,
* event delivery levels,
* UI-first progress.

### 23.3 Multilingual Misclassification

Risk:

* code-switched input causes wrong routing.

Mitigation:

* explicit language fields,
* normalize task specs,
* stricter confirmation threshold,
* preserve product names.

### 23.4 Agent Side Effects

Risk:

* execution agent changes files or performs external actions prematurely.

Mitigation:

* read-only first default,
* permission boundaries,
* stop conditions,
* explicit escalation.

---

## 24. Metrics

### 24.1 Product Metrics

* successful task dispatch rate,
* wrong dispatch rate,
* clarification rate,
* confirmation acceptance rate,
* task completion rate,
* user-initiated stop rate,
* average number of spoken turns per task,
* user status query rate,
* artifact acceptance rate.

### 24.2 Quality Metrics

* task spec completeness score,
* routing accuracy,
* dispatch gate false positive rate,
* dispatch gate false negative rate,
* multilingual classification accuracy,
* average speech response length,
* noise score per session.

### 24.3 Latency Metrics

* STT partial delay,
* classification latency,
* draft generation latency,
* dispatch confirmation latency,
* agent event ingest delay,
* status summary latency.

---

## 25. MVP Scope

### 25.1 MVP Features

1. Voice/text input through communication runtime.
2. Draft task by voice/text.
3. Stage task for Hermes.
4. Confirm before dispatch.
5. Dispatch to Hermes in read-only/proposal mode.
6. Store events in blackboard.
7. Ask status.
8. Stop task.
9. Notify when blocked.
10. Notify when complete.
11. Chinese/English mixed input support.

### 25.2 MVP Exclusions

* multi-agent automatic routing,
* autonomous code modification,
* full artifact review workflow,
* complex parallel task management,
* custom model training,
* mandatory local model dependency,
* voice emotion/personality layer.

Gemma 4 E4B may be used as an optional local classifier, but MVP must still work with rules + hosted fallback only.

---

## 26. Implementation Plan

### Phase 1: Core Runtime

* Build session state manager.
* Build message ingestion API.
* Build interaction classifier with rules + hosted LLM fallback.
* Add optional Gemma 4 E4B local classifier path for the 1s interaction loop.
* Build draft manager.
* Build task spec generator.

### Phase 2: Dispatch Safety

* Build task linter.
* Build routing table.
* Build dispatch gate.
* Build confirmation flow.
* Add read-only first policy.

### Phase 3: Hermes Integration

* Build Hermes adapter.
* Start task from structured packet.
* Capture Hermes events.
* Write events to blackboard.
* Support stop task.

### Phase 4: Quiet Communication

* Build speech policy engine.
* Add delivery levels.
* Add progress summarizer.
* Add status query handling.
* Add blocked/done notifications.

### Phase 5: Agora Integration

* Implement the Agora server using the Agora Python Agent Server SDK.
* Map SDK transcript, turn, interruption, and session lifecycle events into internal runtime events.
* Connect SDK event handlers to the communication runtime.
* Stream only short approved responses back through Agora TTS.
* Validate silent/no-speak behavior for draft updates and low-importance progress.
* Test interruption, barge-in, stop-task, and status-query flows.
* Keep OpenAI-compatible `/v1/chat/completions` only as an optional compatibility/testing endpoint, not the primary integration path.

### Phase 6: Multilingual Hardening

* Add language detection.
* Add code-switch handling.
* Add output language policy.
* Tune confirmations for low-confidence multilingual cases.

---

## 27. Example End-to-End Flow

### User Delegates

User:

> 让 Hermes 看一下 new console 的 Home page，参考 Linear，不要改代码，给我 proposal。

System creates draft:

```json
{
  "target_agent": "hermes",
  "mode": "proposal_only",
  "goal": "Review the new console Home page and propose simplification ideas, using Linear as reference.",
  "constraints": ["Do not modify code"],
  "output_language": "zh-CN"
}
```

Communication brain:

> 已草拟给 Hermes。发送吗？

User:

> Send.

Dispatch gate passes.

Task starts.

Communication brain:

> Sent to Hermes.

### Hermes Progress

Hermes event:

```json
{
  "type": "agent.progress",
  "importance": "low",
  "delivery": "silent_ui",
  "message": "Compared Home page against Linear."
}
```

Communication brain:

> silent

### User Asks Status

User:

> 现在怎么样？

Communication brain:

> Hermes 认为 Home page 的问题是入口太多，主路径不够突出。它正在整理 proposal。

### Hermes Completes

Communication brain:

> Hermes 完成了。有一份 proposal 可以看。

---

## 28. Final Recommendation

Build the system around three hard rules:

1. **Never dispatch raw speech.**
   Always ground into a structured task plan first.

2. **Never let the communication brain be chatty.**
   Speak only for decisions, blockers, completion, status, and risk.

3. **Never let Hermes start in a risky mode.**
   Default to read-only/proposal-first, then escalate with approval.

This gives the product a clear identity:

> A quiet real-time operator layer for supervising long-running AI agents.
