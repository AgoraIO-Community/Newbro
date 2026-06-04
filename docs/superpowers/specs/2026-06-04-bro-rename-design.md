# Bro Rename Design

## Purpose

Let users change a Bro's display name after creation. The current create/connect
dialog shows the Bro name but disables the field for existing Bros, and mobile
Manage Bros implies rename support without exposing it.

## Current Context

- Bro display names are stored as `Persona.name`.
- The backend already exposes `PATCH /api/sessions/{session_id}/personas/{persona_id}`
  through `updatePersona`.
- The route validates non-empty names, owner scope, optional node binding, and
  syncs updated personas into the active runtime session.
- The frontend client already has `updatePersona(sessionId, personaId, payload)`.
- `CreateConnectSheet` uses `updatePersona` only for executor-node binding and
  disables the name field whenever an existing `bro` is passed.
- Desktop Home and Bro Detail display names but do not expose a direct edit
  action.
- Mobile account management says "Rename, remove, reorder", but edit mode only
  supports removal.

## Chosen Approach

Use both rename surfaces:

1. Fix the existing create/connect sheet so existing Bro names can be changed.
2. Add a lightweight Bro edit action from Home/Bro Detail.
3. Add mobile Manage Bros rename support alongside removal.

This addresses the immediate broken dialog while making rename discoverable
without requiring a reconnect/setup path.

## Architecture

Do not add a new protocol model or runtime concept. Rename is a persona
metadata update owned by the public session/persona API.

The frontend calls:

```ts
updatePersona(sessionId, bro.id, { name: trimmedName })
```

Then it refreshes shell state through the existing `refreshShellSession`
callback. The refreshed `SessionSnapshot.personas` remains the source of truth
for all displayed Bro names.

Communication Brain, Execution Brain, executor scheduling, and executor-node
bindings are not changed.

## UI Behavior

### Create / Connect Sheet

For existing Bros, keep the name input editable while the sheet is idle and no
connect credentials have been issued. Disable it only while a sheet operation is
busy, after commands are issued, or after the setup flow is completed.

If the user changes the name before reconnect/setup:

- trim and validate the name
- call `updatePersona`
- continue the connect/setup flow if the user clicked create/connect
- refresh the shell session after the update

For existing Bros that already have a node and the sheet auto-reveals connect
settings, Step 1 must expose a compact "Save name" control. This keeps rename
available even when the connect command is revealed automatically and the main
footer action is `Done`.

### Desktop Home / Detail

Add a compact edit action for runtime Bros. It opens an Edit Bro dialog with:

- current name
- Save
- Cancel
- empty-name validation
- API error display

The dialog should close only after `updatePersona` and `refreshShellSession`
complete.

### Mobile Manage Bros

In mobile edit mode, expose rename separately from remove. Removal stays behind
the existing confirmation. Rename opens the same logical edit flow and calls the
same API path.

Reorder remains out of scope for this change.

## Data Flow

1. User opens rename from the create/connect sheet, Home, Bro Detail, or mobile
   Manage Bros.
2. UI initializes the input from the current runtime Bro/persona name.
3. User submits a non-empty name.
4. UI calls `updatePersona(sessionId, personaId, { name })`.
5. UI calls `refreshShellSession`.
6. UI closes the dialog/sheet rename state after refresh succeeds.
7. Home cards, Bro Detail headers, mobile thread headers, thread drawers, voice
   labels, and recents render from the refreshed snapshot.

Do not use local-only optimistic name state. The backend projection is the
canonical state.

## Error Handling

- Empty or whitespace-only names are rejected in the UI before calling the API.
- API errors remain visible in the active dialog or sheet.
- The UI does not invent fallback names.
- Historical executor-native thread titles, thread ids, and task titles are not
  rewritten by this feature.

## Testing

Add focused frontend tests:

- Desktop edit flow calls `updatePersona("session-existing", "forge", { name:
  "Scout" })`, refreshes the session, and shows `Scout`.
- Existing create/connect sheet allows changing an existing Bro name instead of
  disabling the input.
- Mobile Manage Bros exposes rename and remove separately, and rename calls the
  same PATCH path.

Backend tests are not required unless implementation reveals a gap in the
existing update route. The current route already validates empty names, owner
scope, and session sync.

## Out Of Scope

- Reordering Bros.
- Renaming executor nodes.
- Rewriting historical thread/task titles.
- Changing persona ids or Bro detail session ids for name-only edits.
- Adding fallback display-name behavior.
