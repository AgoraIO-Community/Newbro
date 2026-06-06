# Cardputer Thread Picker — Design

**Date:** 2026-06-05
**Status:** Approved design, ready for implementation planning
**Scope:** Add a thread-picker screen so that, after choosing a Bro, the user selects one of that Bro's existing threads, and the chat targets the selected thread. The device never creates threads.

## 1. Goal & motivation

The server rejects direct-executor instructions that declare no thread intent:
`409 {"detail":"Direct Bro Detail instruction requires explicit thread intent."}`.
The device currently sends neither `create_new_thread` nor a `target_thread_id`, so push-to-talk fails. Rather than auto-create threads, the device should **list the selected Bro's existing threads, let the user pick one, and target it** (`target_thread_id`). Threads are started in the web app; the device only resumes them.

## 2. Flow

```
Bro list ──Enter──▶ Thread list (for that Bro) ──Enter──▶ Chat (targets picked thread_id)
   ▲                      │                                    │
   └────────Back──────────┘◀──────────────Back────────────────┘
```

- Selecting a Bro fetches the session snapshot, extracts that Bro's threads, and shows the **Thread list**.
- Selecting a thread opens the **Chat**, bound to that `thread_id`; push-to-talk sends with `target_thread_id` set.
- Back from Chat returns to the Thread list; Back from the Thread list returns to the Bro list.
- The device never sends `create_new_thread`.

## 3. Data (host-tested, `nb_session_json`)

The session snapshot (`GET /api/sessions/{id}`, already polled by the device) contains `bro_threads[]`. Relevant fields: `thread_id`, `persona_id`, `title`, `preview` (string|null), `status`, `updated_at` (string|null).

Add:

```cpp
struct ThreadInfo {
  std::string id;
  std::string title;
  std::string preview;   // empty if null
  std::string status;
  std::string updatedAt; // ISO-8601, "" if null
};

// Threads for one persona, newest-first (by updated_at desc; "" sorts last).
bool parseBroThreads(const std::string &snapshotJson, const std::string &personaId,
                     std::vector<ThreadInfo> &out);
```

`parseBroThreads` uses an ArduinoJson **filtered** parse (only `bro_threads` and the listed fields) to bound RAM, keeps entries whose `persona_id` matches, and sorts by `updated_at` descending (ISO-8601 sorts lexicographically; empty `updated_at` sorts last).

## 4. Thread targeting (host-tested)

`buildAudioQuery` and `buildTextBody` gain a `targetThreadId` argument:
- `buildAudioQuery(personaId, meta, targetThreadId)` appends `&target_thread_id=<id>` and **does not** send `create_new_thread`.
- `buildTextBody(personaId, text, targetThreadId)` sets `target_thread_id` and `create_new_thread=false`.

`NewbroClient` methods take the thread id:
- `sendAudio(sessionId, personaId, targetThreadId, meta, pcm, len, transcriptOut)`.
- `sendText(sessionId, personaId, targetThreadId, text)`.
- New `getThreads(sessionId, personaId, std::vector<ThreadInfo> &out)` — `GET /api/sessions/{id}` then `parseBroThreads`.

## 5. Screens & wiring (device glue)

- **`ThreadListScreen`** (new, mirrors `BroListScreen`): header (Bro name + "Threads"), rows of **title + one-line preview** (preview truncated to width), selection highlight, `↑/↓` to move, `Enter` to pick (invokes `onPick(ThreadInfo)`), Back (invokes `onBack`). Reuses `nb_ui_layout` (`listScrollTop`/`moveSelection`/`truncate`). Empty list → centered "No threads — start one in the web app".
- **`ChatScreen`** gains `setThread(const std::string &threadId)`; the voice turn passes it as `target_thread_id`.
- **`Router`/`main.cpp`**: opening a Bro now calls `getThreads`; on success shows `ThreadListScreen` (or the empty state); picking a thread sets `g_threadId` + opens `ChatScreen`; `runVoiceTurn` sends with `g_threadId`. Back transitions: Chat → Thread list, Thread list → Bro list.

## 6. Error handling

- Snapshot fetch fails → Thread list shows "couldn't load threads"; Back returns to the Bro list.
- No threads for the Bro → the empty message (per "device never creates threads"; start one in the web app).
- A thread whose executor is offline → the existing audio error path surfaces the server detail (already implemented).

## 7. Testing

- Host unit tests: `parseBroThreads` (filter by persona, newest-first sort, null preview/updated_at, empty result); `buildAudioQuery`/`buildTextBody` with a thread id (and no `create_new_thread`); `NewbroClient::getThreads` over a fake transport returning a snapshot.
- Device glue (`ThreadListScreen`, router wiring) verified by device compile + an on-device run: pick a Bro → see its threads → pick one → push-to-talk → transcript + reply (the 409 should be gone).

## 8. Out of scope (future)

- Creating threads from the device.
- Thread continuity tracking beyond the picked thread (each chat session is bound to the one picked thread).
- Showing per-thread timeline/history on the device beyond the latest turn already rendered in chat.
- Verifying whether `POST /bro-threads/{id}/open` is required before targeting — to be checked during implementation; added only if the instruction needs it.
