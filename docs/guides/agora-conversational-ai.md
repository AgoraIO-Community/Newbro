# Agora Conversational AI

This guide documents the supported Newbro integration path for the first-party
`agora-convoai` connector module.

## Example Shape

The supported backend path is now the headless connector host plus the first-party
Agora connector module under:

- `src/newbro/connectors/host/`
- `src/newbro/connectors/voice/agora_convoai/`

That connector module owns:

- Agora ConvoAI lifecycle via the Python SDK module `agora_agent`
- Newbro connector binding
- the public custom-LLM callback URL used by Agora
- proactive notification speech through the local ConvoAI session

The active browser UI lives under:

- `src/newbro/ui/`

The connector host runs separately from the main Newbro API server:

- Newbro server: `8000`
- Connector host: `8010`

The `agora-convoai` module exposes headless routes:

- `GET /api/connectors/agora-convoai/config`
- `POST /api/connectors/agora-convoai/sessions/prepare`
- `POST /api/connectors/agora-convoai/sessions/activate`
- `POST /api/connectors/agora-convoai/sessions/stop`
- `POST /api/connectors/agora-convoai/chat/completions`

## Behavior

- one live Agora agent binds to one Newbro session
- duplicate runtime-agent bindings are rejected
- Agora voice input is represented as typed Newbro runtime events
- Newbro owns `RuntimeDecision.should_speak`; the connector does not decide
  whether a transcript should produce TTS
- final transcript meaning is interpreted by the Communication Brain
  interaction classifier; runtime code applies deterministic speech policy to
  that structured classifier output and current state
- the connector module owns Agora auth and calls Agora APIs on behalf of the integration
- browser ConvoAI voice sessions are Bro-detail scoped; the UI binds
  `/api/sessions/{session_id}/voice-target` to the current Bro before Start is
  available
- ConvoAI turns use that bound Bro as the target persona and must not ask the
  user to pick a Bro while the Bro detail context exists
- partial transcripts, speech lifecycle events, and session lifecycle events are
  silent unless the runtime returns a spoken decision
- `/chat/completions` is compatibility glue for Agora's custom LLM surface, not
  the source of truth for transcript finality, quietness, or Bro routing
- proactive notification delivery is triggered only for Newbro notification events
- normal chat replies are not replayed through `/speak`
- the browser UI is a client of the connector host and is not part of the connector boundary

## LLM Path

For this module, Agora does not call OpenAI directly.

Instead, `POST /api/connectors/agora-convoai/sessions/activate` reserves a connector
binding first and builds:

```text
${SYNAPSE_CONNECTOR_PUBLIC_BASE_URL}/api/connectors/agora-convoai/chat/completions?binding_id=...
```

and passes that full URL into the Agora SDK as the OpenAI-compatible LLM endpoint.

When Agora calls that URL:

1. the connector resolves `binding_id`
2. the connector resolves the bound Newbro session's current Bro voice target
3. the connector logs redacted callback diagnostics for adapter debugging
4. the connector translates explicit event metadata into an `AgoraVoiceEvent`
   for the bound external Newbro session on `8000`
5. if no explicit event metadata is present, the compatibility adapter treats
   the custom LLM callback as a compatibility turn candidate, coalesces repeated
   callback updates for the same binding, then submits only the latest stable
   candidate as `stt.final`
6. Newbro returns a `RuntimeDecision`
7. the connector speaks the decision text through the active Agora runtime only
   when `RuntimeDecision.should_speak` is true

For the quiet runtime path, partial transcript updates, lifecycle events, draft
micro-updates, and other `should_speak=false` decisions return an empty response
to the compatibility caller. Short TTS responses are reserved for meaningful
communication, confirmation, clarification, blocked state, completion, status,
stop/cancel acknowledgement, permission/risk, and urgent events. This is not a
one-reply cap; multiple replies are valid when the user produces multiple
meaningful turns.

The stable backend event endpoint is:

```text
POST /api/sessions/{session_id}/agora-events
```

It accepts `stt.partial`, `stt.final`, speech lifecycle, interruption, and
session lifecycle events. `stt.final` is the transcript event that can stage or
update work after interaction classification. The runtime does not use phrase
lists, transcript length, language-ending checks, duplicate-text rules, or
semantic transcript keywords to decide whether to speak.

The browser ConvoAI toolkit transcript stream is display-only in the current
integration. Live testing showed toolkit `user.transcription` items can mark
growing fragments as `metadata.final=true`, so the browser must not submit those
items directly as backend `stt.final` events.

The connector's custom LLM callback is the compatibility final-turn source and
is debounced because live ConvoAI can call the OpenAI-compatible endpoint
repeatedly with growing transcript text. The runtime still owns classification
and `should_speak`; the connector must not use transcript text length,
punctuation, language, duplicate text, or keywords to decide quietness.
The fallback silence window is configured by
`connectors.agora-convoai.chat_completion_turn_silence_seconds` and defaults to
`6.0` seconds; explicit SDK-style finality events bypass this compatibility
window.

The installed `agora_agent.AsyncAgentSession` event callback surface exposes
`started`, `stopped`, and `error` lifecycle callbacks. It does not expose a
Python transcript/finality callback hook in the currently installed SDK surface,
so transcript events are modeled at the Newbro adapter boundary and covered by
fake-backed tests until an SDK transcript callback is available.

`OPENAI_API_KEY` and optional `SYNAPSE_OPENAI_BASE_URL` therefore belong to the
separate Newbro server on `8000` for model-backed communication paths, not the
connector host on `8010`.

## Notification Delivery

The connector watches the Newbro session stream and forwards only notification-origin
text to the live Agora session.

When such an event arrives, the connector calls the local ConvoAI service `say()`
path for the started SDK session. This keeps Agora auth inside the connector host
while sourcing notification text from the external Newbro server.

## Identity Model

This example now mirrors the official sample's split identity model:

- RTC user uid: numeric uid
- RTM user uid: `<user_uid>-<channel>`
- agent RTC uid: configured agent uid
- agent RTM uid: `<agent_uid>-<channel>`

The frontend uses the agent RTM uid for toolkit messaging calls and the agent RTC uid for media/transcript identity.

The main workbench under `src/newbro/ui/` uses Bro detail as the ConvoAI entry
point. That UI path:

- exposes ConvoAI Start only on Bro detail pages
- binds the current Bro detail page as the voice target before Start
- clears the voice target when leaving that Bro detail context
- calls the connector host through `/api/connectors/agora-convoai/*` when starting
  a Bro-detail voice session
- keeps the shell on its existing `POST /api/sessions` session before, during,
  and after voice mode
- sends that current `synapse_session_id` into connector session prepare so the
  voice binding attaches to the existing Newbro session
- defaults the Agora `channel_name` to that `synapse_session_id` when the
  browser does not provide an explicit channel override
- tears down only the live voice transport and connector binding on `Stop`
  without swapping the shell to a different Newbro session
- uses Newbro conversation history plus Newbro user/assistant stream events
  for the left-pane interaction memory while the Agora toolkit remains
  responsible for browser-local RTC/RTM/session behavior

## Run

Configure `~/.newbro/.env` and `~/.newbro/config.yaml`, then run:

```bash
./newbro setup
./newbro connector setup
./newbro start
```

For development with frontend + connector together:

```bash
./newbro dev
```

For frontend development, use the active shell under `src/newbro/ui/` through `./newbro dev`.

The connector host reads its live config from the shared `~/.newbro/config.yaml`
file and shared runtime env from `~/.newbro/.env`.

For live Agora sessions, `SYNAPSE_CONNECTOR_PUBLIC_BASE_URL` must be a public URL
that can reach the connector host.

For this example, Newbro fixes `connectors.agora-convoai.convoai_area` to `US`.

## Ownership Note

The active browser UI under `src/newbro/ui/` is the supported frontend. It is a
client of the connector host and is not part of the connector-host architecture
boundary.
