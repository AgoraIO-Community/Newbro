import { afterEach, describe, expect, it, vi } from "vitest";

class MockWebSocket {
  static readonly OPEN = 1;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readonly readyState = MockWebSocket.OPEN;
  readonly addEventListener = vi.fn();
  readonly close = vi.fn();
  readonly send = vi.fn();

  constructor(url: string | URL) {
    this.url = String(url);
    MockWebSocket.instances.push(this);
  }
}

function okJsonResponse(payload: object): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

describe("session-client transport base URL handling", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
  });

  it("uses relative HTTP paths and the current origin websocket URL by default", async () => {
    const fetchMock = vi.fn(async () => okJsonResponse({ session_id: "session-1" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    const client = await import("./session-client");

    await client.createSession();
    client.openSessionStream("session-1", {
      onOpen: vi.fn(),
      onMessage: vi.fn(),
      onClose: vi.fn(),
      onError: vi.fn(),
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions", {
      method: "POST",
    });
    expect(MockWebSocket.instances[0]?.url).toBe(
      `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/api/sessions/session-1/stream`,
    );
  });

  it("uses the configured HTTPS base URL for fetches and WSS for websocket streams", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    const fetchMock = vi.fn(async () => okJsonResponse({ session_id: "session-1" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockWebSocket);

    const client = await import("./session-client");

    await client.createSession();
    client.openSessionStream("session-1", {
      onOpen: vi.fn(),
      onMessage: vi.fn(),
      onClose: vi.fn(),
      onError: vi.fn(),
    });

    expect(fetchMock).toHaveBeenCalledWith("https://api.example.com/api/sessions", {
      method: "POST",
    });
    expect(MockWebSocket.instances[0]?.url).toBe("wss://api.example.com/api/sessions/session-1/stream");
  });

  it("normalizes trailing slashes on the configured backend base URL", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com/runtime/");
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        session_id: "session-1",
        conversation_history: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");

    await client.getConversationSnapshot("session-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.com/runtime/api/sessions/session-1/conversation",
    );
  });

  it("builds an executor run command from the effective backend base URL", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com/runtime/");
    const client = await import("./session-client");

    expect(
      client.buildExecutorRunCommand("node-1", "tok'en", {
        enabledExecutors: ["acpx"],
        acpxAgent: "openclaw",
        audioLanguage: "zh",
        whisperModel: "small",
      }),
    ).toBe(
      "newbro executor run --base-url 'https://api.example.com/runtime' --node-id 'node-1' --token 'tok'\"'\"'en' --enabled-executor 'acpx' --acpx-agent 'openclaw' --audio-language 'zh' --whisper-model 'small'",
    );
  });

  it("uses the Newbro service port for executor commands during local Vite dev", async () => {
    const client = await import("./session-client");

    expect(client.buildExecutorRunCommand("node-1", "token-1")).toBe(
      "newbro executor run --base-url 'http://localhost:8000' --node-id 'node-1' --token 'token-1'",
    );
  });

  it("calls the explicit connect-command reveal endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        node: {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          acpx_agent: null,
          connected_executors: [],
          connection_status: "disconnected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
        token: "token-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    const revealed = await client.revealExecutorNodeConnectCommand("session-1", "node-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/executor-nodes/node-1/connect-command", {
      method: "POST",
    });
    expect(revealed.token).toBe("token-1");
  });

  it("includes the target persona on websocket messages when provided", async () => {
    const client = await import("./session-client");
    const socket = { send: vi.fn() } as unknown as WebSocket;

    client.sendSocketMessage(socket, "req-1", "Run this", "forge");

    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({
      type: "send_message",
      request_id: "req-1",
      text: "Run this",
      target_persona_id: "forge",
    }));
  });

  it("submits executor text instructions through the HTTP executor endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        instruction_id: "txt-1",
        target_persona_id: "forge",
        status: "accepted",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    await client.submitExecutorTextInstruction("session-1", {
      targetPersonaId: "forge",
      text: "continue directly",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/executor-text-instructions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_persona_id: "forge",
        target_thread_id: null,
        create_new_thread: false,
        text: "continue directly",
      }),
    });
  });

  it("submits executor audio instructions with the selected thread target", async () => {
    const audio = new Blob([new Uint8Array([0, 0, 1, 0])], { type: "audio/pcm" });
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        audio_instruction_id: "aud-1",
        target_persona_id: "forge",
        target_thread_id: "bro-thread-1",
        status: "accepted",
        duration_ms: 1,
        size_bytes: 4,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    await client.submitExecutorAudioInstruction("session-1", {
      targetPersonaId: "forge",
      targetThreadId: "bro-thread-1",
      pcm16: audio,
      durationMs: 1,
      sampleRate: 16000,
      numChannels: 1,
      samplesPerChannel: 16,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [url, init] = call as unknown as [string, RequestInit];
    expect(url).toBe(
      "/api/sessions/session-1/executor-audio-instructions?target_persona_id=forge&duration_ms=1&sample_rate=16000&num_channels=1&samples_per_channel=16&target_thread_id=bro-thread-1",
    );
    expect(init).toEqual({
      method: "POST",
      headers: { "Content-Type": "audio/pcm" },
      body: audio,
    });
  });

  it("opens a bro thread through the hydration endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        session_id: "session-1",
        tasks: [],
        execution_sessions: [],
        execution_runs: [],
        execution_modes: [],
        bindings: [],
        summaries: [],
        notification_candidates: [],
        bro_threads: [],
        personas: [],
        interaction_requests: [],
        attention_items: [],
        agent_events: [],
        executor_capabilities: [],
        executor_nodes: [],
        draft_session: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    await client.openBroThread("session-1", {
      targetPersonaId: "forge",
      threadId: "codex-import-1",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/bro-threads/codex-import-1/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_persona_id: "forge" }),
    });
  });

  it("closes a bro thread through the selected-thread endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        session_id: "session-1",
        tasks: [],
        execution_sessions: [],
        execution_runs: [],
        execution_modes: [],
        bindings: [],
        summaries: [],
        notification_candidates: [],
        bro_threads: [],
        personas: [],
        interaction_requests: [],
        attention_items: [],
        agent_events: [],
        executor_capabilities: [],
        executor_nodes: [],
        draft_session: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    await client.closeBroThread("session-1", {
      targetPersonaId: "forge",
      threadId: "codex-import-1",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/bro-threads/codex-import-1/open", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_persona_id: "forge" }),
    });
  });

  it("submits task commands to the session commands endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        command_id: "cmd-1",
        status: "accepted",
        affected_task_ids: ["task-1"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./session-client");
    await client.submitTaskCommand("session-1", {
      command_type: "cancel_task",
      task_id: "task-1",
      reason: "Stopped from Bro detail Runner Brain.",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/session-1/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command_type: "cancel_task",
        task_id: "task-1",
        reason: "Stopped from Bro detail Runner Brain.",
      }),
    });
  });
});

describe("session-client HTTP error formatting", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it.each([
    [JSON.stringify({ detail: "Not found." }), "Not found."],
    [JSON.stringify({ detail: JSON.stringify({ detail: "core: db failed, task not found", reason: "TaskNotFound" }) }), "core: db failed, task not found"],
    [JSON.stringify({ reason: "TaskNotFound" }), "TaskNotFound"],
    [JSON.stringify({ detail: "" }), "Request failed with status 404"],
    ["plain failure", "plain failure"],
  ])("formats failed response body %s", async (body, expected) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 404 })));
    const client = await import("./session-client");

    await expect(client.getSessionSnapshot("session-missing")).rejects.toThrow(expected);
  });
});
