import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider } from "@tanstack/react-router";
import App from "../App";
import { buildBroCardModels } from "../components/newbro";
import { buildBroTaskRecords, buildBroThreadRecords } from "../components/newbro/adapters";
import { getRouter } from "../router";

const socketHarness = vi.hoisted(() => {
  const state = {
    handlers: null as null | {
      onMessage: (event: any) => void;
      onClose: () => void;
      onError: () => void;
    },
    socket: {
      readyState: 1,
      close: vi.fn(),
    },
    reset() {
      state.handlers = null;
      state.socket.close.mockClear();
    },
  };
  return state;
});

const voiceHarness = vi.hoisted(() => ({
  rtcClient: {
    on: vi.fn(),
    subscribe: vi.fn(async () => {}),
    join: vi.fn(async () => {}),
    publish: vi.fn(async () => {}),
    leave: vi.fn(async () => {}),
  },
  micTrack: {
    stop: vi.fn(),
    close: vi.fn(),
    setEnabled: vi.fn(async () => {}),
    setMuted: vi.fn(async () => {}),
  },
  rtmClient: {
    login: vi.fn(async () => {}),
    subscribe: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
  },
  voiceAi: {
    on: vi.fn(),
    subscribeMessage: vi.fn(),
    unsubscribe: vi.fn(),
    destroy: vi.fn(),
  },
  reset() {
    voiceHarness.rtcClient.on.mockClear();
    voiceHarness.rtcClient.subscribe.mockClear();
    voiceHarness.rtcClient.join.mockClear();
    voiceHarness.rtcClient.publish.mockClear();
    voiceHarness.rtcClient.leave.mockClear();
    voiceHarness.micTrack.stop.mockClear();
    voiceHarness.micTrack.close.mockClear();
    voiceHarness.micTrack.setEnabled.mockClear();
    voiceHarness.micTrack.setMuted.mockClear();
    voiceHarness.rtmClient.login.mockClear();
    voiceHarness.rtmClient.subscribe.mockClear();
    voiceHarness.rtmClient.logout.mockClear();
    voiceHarness.voiceAi.on.mockClear();
    voiceHarness.voiceAi.subscribeMessage.mockClear();
    voiceHarness.voiceAi.unsubscribe.mockClear();
    voiceHarness.voiceAi.destroy.mockClear();
  },
}));

const clientMock = vi.hoisted(() => ({
  bootstrapPublicUser: vi.fn(),
  signupPublicUser: vi.fn(),
  getCurrentUser: vi.fn(),
  logoutPublicUser: vi.fn(),
  getSessionSnapshot: vi.fn(),
  getConversationSnapshot: vi.fn(),
  openBroThread: vi.fn(),
  closeBroThread: vi.fn(),
  openSessionStream: vi.fn((_sessionId: string, handlers: any) => {
    socketHarness.handlers = handlers;
    return socketHarness.socket as any;
  }),
  sendSocketMessage: vi.fn(),
  sendSocketDraftAsrTurn: vi.fn(),
  submitExecutorAudioInstruction: vi.fn(),
  submitExecutorTextInstruction: vi.fn(),
  createPersona: vi.fn(),
  updatePersona: vi.fn(),
  createExecutorNode: vi.fn(),
  revealExecutorNodeConnectCommand: vi.fn(),
  buildExecutorConnectCommands: vi.fn(() => ({
    installConnect: "curl -fsSL https://raw.githubusercontent.com/AgoraIO-Community/Newbro/main/scripts/install-newbro-cli.sh | sh -s -- executor run --node-id node-1 --token token-1",
    runOnly: "newbro executor run --node-id node-1 --token token-1",
  })),
  sendDraft: vi.fn(async () => ({ task_id: "task-1" })),
  clearDraft: vi.fn(async () => ({ status: "cleared" })),
  setVoiceTarget: vi.fn(async () => undefined),
  clearVoiceTarget: vi.fn(async () => undefined),
}));

const connectorMock = vi.hoisted(() => ({
  getConnectorConfig: vi.fn(async () => ({
    ready: true,
    service_base_url: "https://connectors.example.com",
    defaults: {},
    missing_requirements: [],
  })),
  prepareConnectorSession: vi.fn(async () => ({
    prepared_session_id: "prepared-1",
    app_id: "agora-app",
    channel_name: "voice-room",
    token: "voice-token",
    uid: 101,
    user_rtm_uid: "101-voice-room",
    agent: { uid: "9001" },
    agent_rtm_uid: "9001-voice-room",
    enable_string_uid: false,
    profile: "VOICE",
    display_name: "Newbro Tester",
    diagnostics: {},
  })),
  activateConnectorSession: vi.fn(async () => ({
    prepared_session_id: "prepared-1",
    binding_id: "binding-1",
    synapse_session_id: "session-existing",
    runtime_session_id: "runtime-1",
    chat_completions_url: "https://gateway.example.com/chat",
    app_id: "agora-app",
    channel_name: "voice-room",
    token: "voice-token",
    uid: 101,
    user_rtm_uid: "101-voice-room",
    agent: { uid: "9001" },
    agent_rtm_uid: "9001-voice-room",
    enable_string_uid: false,
    profile: "VOICE",
    display_name: "Newbro Tester",
    diagnostics: {},
  })),
  stopConnectorSessionBeacon: vi.fn(() => true),
}));

const runtimeMock = vi.hoisted(() => ({
  loadAgoraBrowserStack: vi.fn(async () => ({
    AgoraRTC: {
      createClient: vi.fn(() => voiceHarness.rtcClient),
      createMicrophoneAudioTrack: vi.fn(async () => voiceHarness.micTrack),
    },
    AgoraRTM: {
      RTM: vi.fn().mockImplementation(function MockRTM() {
        return voiceHarness.rtmClient;
      }),
    },
    AgoraVoiceAI: {
      init: vi.fn(async () => voiceHarness.voiceAi),
    },
    AgoraVoiceAIEvents: {
      TRANSCRIPT_UPDATED: "TRANSCRIPT_UPDATED",
      AGENT_STATE_CHANGED: "AGENT_STATE_CHANGED",
      AGENT_ERROR: "AGENT_ERROR",
      MESSAGE_ERROR: "MESSAGE_ERROR",
      AGENT_INTERRUPTED: "AGENT_INTERRUPTED",
      DEBUG_LOG: "DEBUG_LOG",
    },
    TranscriptHelperMode: { AUTO: "AUTO" },
  })),
  teardownVoiceSession: vi.fn(async () => {}),
}));

vi.mock("../lib/session-client", () => clientMock);
vi.mock("../lib/connector-client", () => connectorMock);
vi.mock("../lib/voice-runtime", () => runtimeMock);

function usableExecutorNode(overrides: Record<string, unknown> = {}) {
  return {
    node_id: "node-forge",
    name: "Workshop Mini",
    enabled_executors: ["codex"],
    connected_executors: ["codex"],
    connected_executor_capabilities: [
      {
        executor_type: "codex",
        supports_resume: true,
        supports_follow_up: true,
        supports_audio_instruction: true,
        supports_pause: true,
        supports_cancel: true,
      },
    ],
    connection_status: "connected",
    token_hint: "tok...0001",
    last_connected_at: "2026-05-23T20:00:00Z",
    last_seen_at: "2026-05-23T20:00:00Z",
    acpx_agent: null,
    ...overrides,
  };
}

function emptySessionSnapshot(sessionId: string) {
  return {
    session_id: sessionId,
    tasks: [],
    execution_sessions: [],
    execution_runs: [],
    execution_modes: [],
    bindings: [],
    summaries: [],
    notification_candidates: [],
    bro_threads: [],
    bro_timeline_turns: [],
    personas: [],
    interaction_requests: [],
    attention_items: [],
    executor_capabilities: [],
    executor_nodes: [],
  };
}

function timelineTurn(overrides: Record<string, any> = {}) {
  const threadId = overrides.thread_id ?? "codex-import-history";
  const turnId = overrides.executor_turn_id ?? "turn-1";
  const userText = overrides.userText as string | undefined;
  const assistantText = overrides.assistantText as string | undefined;
  return {
    turn_id: `${threadId}:codex:${turnId}`,
    thread_id: threadId,
    persona_id: "forge",
    executor_id: "codex",
    owner: "executor",
    client_request_id: null,
    executor_thread_id: overrides.executor_thread_id ?? `native-${threadId}`,
    executor_turn_id: turnId,
    input_modality: userText ? "text" : "unknown",
    user: userText
      ? {
          message_id: `${threadId}:${turnId}:user`,
          role: "user",
          kind: "text",
          text: userText,
          transcript: null,
          audio_id: null,
          duration_ms: null,
          created_at: overrides.created_at ?? "2026-05-26T22:01:00+00:00",
          updated_at: null,
          status: "completed",
          metadata: {},
        }
      : null,
    assistant: assistantText
      ? {
          message_id: `${threadId}:${turnId}:assistant`,
          role: "assistant",
          kind: "text",
          text: assistantText,
          transcript: null,
          audio_id: null,
          duration_ms: null,
          created_at: overrides.updated_at ?? "2026-05-26T22:02:00+00:00",
          updated_at: null,
          status: "completed",
          metadata: {},
        }
      : null,
    task: null,
    status: overrides.status ?? "completed",
    created_at: overrides.created_at ?? "2026-05-26T22:01:00+00:00",
    updated_at: overrides.updated_at ?? "2026-05-26T22:02:00+00:00",
    metadata: { assistant_title: userText, ...(overrides.metadata ?? {}) },
    ...overrides,
  };
}

function forgeSnapshot(sessionId: string, node = usableExecutorNode()) {
  return {
    ...emptySessionSnapshot(sessionId),
    personas: [
      {
        persona_id: "forge",
        name: "Forge",
        avatar: "bro",
        base_prompt: "",
        executor_node_id: node.node_id,
        bro_detail_session_id: "detail-forge",
        status: "idle",
        current_task_id: null,
      },
    ],
    executor_nodes: [node],
  };
}

function activeForgeSnapshot(sessionId: string, node = usableExecutorNode()) {
  return {
    ...forgeSnapshot(sessionId, node),
    personas: [
      {
        persona_id: "forge",
        name: "Forge",
        avatar: "bro",
        base_prompt: "",
        executor_node_id: node.node_id,
        bro_detail_session_id: "detail-forge",
        status: "busy",
        current_task_id: "task-1",
      },
    ],
    tasks: [
      {
        task_id: "task-1",
        root_task_id: "task-1",
        parent_task_id: null,
        title: "Active Codex task",
        goal: "Keep working",
        status: "running",
        priority: 0,
        interruptible: true,
        requires_confirmation: false,
        preferred_executor: "codex",
        session_affinity: null,
        task_revision: 1,
        latest_instruction: null,
        metadata: { persona_id: "forge" },
      },
    ],
    execution_sessions: [
      {
        execution_session_id: "exec-1",
        task_id: "task-1",
        base_executor_id: "codex",
        executor_node_id: node.node_id,
        continuity_key: null,
        run_ids: ["run-1"],
        active_run_id: "run-1",
        latest_run_id: "run-1",
        latest_resume_handle: null,
        queued_run_request: null,
      },
    ],
    bro_threads: [
      {
        thread_id: "exec-1",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: node.node_id,
        execution_session_id: "exec-1",
        status: "running",
        title: "Active Codex task",
        preview: "Keep working",
        progress: 60,
        task_ids: ["task-1"],
        active_task_id: "task-1",
        latest_task_id: "task-1",
        has_resume_handle: false,
        updated_at: null,
        diagnostics: {},
      },
    ],
    execution_runs: [
      {
        run_id: "run-1",
        task_id: "task-1",
        execution_session_id: "exec-1",
        executor_type: "codex",
        status: "running",
        claimed_by: null,
        run_revision: 1,
        latest_progress_message: null,
        output_summary: null,
        block_reason: null,
        failure_reason: null,
        metadata: {},
      },
    ],
  };
}

describe("Newbro artboard shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    socketHarness.reset();
    voiceHarness.reset();
    window.history.replaceState({}, "", "/");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(async () => undefined) },
    });
    clientMock.bootstrapPublicUser.mockResolvedValue({
      user: { user_id: "user-1" },
      session_id: "session-1",
      default_persona_id: null,
      default_bro_detail_session_id: null,
    });
    clientMock.signupPublicUser.mockResolvedValue({ user: { user_id: "user-1", email: "user@example.com" } });
    clientMock.getCurrentUser.mockResolvedValue({ user: { user_id: "user-1" } });
    clientMock.logoutPublicUser.mockResolvedValue({ ok: true });
    clientMock.getSessionSnapshot.mockImplementation(async (sessionId: string) => (
      sessionId === "session-existing" ? forgeSnapshot(sessionId) : emptySessionSnapshot(sessionId)
    ));
    clientMock.closeBroThread.mockImplementation(async () => forgeSnapshot("session-existing"));
    clientMock.getConversationSnapshot.mockImplementation(async (sessionId: string) => ({
      session_id: sessionId,
      conversation_history: [],
    }));
    clientMock.openBroThread.mockImplementation(async () => activeForgeSnapshot("session-existing"));
    clientMock.createExecutorNode.mockResolvedValue({
      node: usableExecutorNode({
        node_id: "node-1",
        name: "Local node",
        connected_executors: [],
        connection_status: "disconnected",
        last_connected_at: null,
        last_seen_at: null,
      }),
      token: "token-1",
    });
    clientMock.revealExecutorNodeConnectCommand.mockResolvedValue({
      node: usableExecutorNode({ node_id: "node-1", name: "Local node" }),
      token: "token-1",
    });
    clientMock.submitExecutorTextInstruction.mockResolvedValue({
      instruction_id: "txt-1",
      target_persona_id: "forge",
      target_thread_id: "exec-1",
      status: "accepted",
    });
    clientMock.updatePersona.mockResolvedValue({});
  });

  it("boots into the artboarded empty workspace and preserves sid", async () => {
    render(<App />);

    expect(await screen.findByText("You don't have a bro yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create your first bro" })).toBeInTheDocument();
    expect(screen.queryByTestId("shell-connecting")).not.toBeInTheDocument();
    expect(screen.queryByTestId("shell-api-error")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?sid=session-1");
  });

  it("shows the artboarded invitation sign-in state when auth is required", async () => {
    clientMock.bootstrapPublicUser.mockRejectedValueOnce(new Error("Authentication required"));

    render(<App />);

    expect((await screen.findAllByRole("heading", { name: /Hi there\./ })).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Invitation code", { selector: "input" }), { target: { value: "k7p4q9r8" } });
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));

    await waitFor(() => expect(clientMock.signupPublicUser).toHaveBeenCalledWith("user@example.com", "K7P4Q9R8"));
  });

  it("waits for the first node connection before creating the first Bro", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Create your first bro" }));
    fireEvent.click(await screen.findByTestId("bro-setup-create-node"));

    await waitFor(() => expect(clientMock.createExecutorNode).toHaveBeenCalledWith("session-1", {
      name: "atlas local node",
      enabled_executors: ["codex"],
    }));
    expect(clientMock.createPersona).not.toHaveBeenCalled();
    expect(await screen.findByText(/install-newbro-cli\.sh/)).toBeInTheDocument();
    expect(screen.getByText(/New to Newbro CLI/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /(Copy|Copied) install \+ connect/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy run-only command/i })).toBeInTheDocument();
    expect(screen.getByText(/The Bro appears after the first successful connection/)).toBeInTheDocument();
  });

  it("shows mobile install/connect instructions before creating the first Bro", async () => {
    window.history.replaceState({}, "", "/mobile?sid=session-1");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByTestId("mobile-empty-workspace")).toHaveTextContent("install/connect command");
    fireEvent.click(screen.getByRole("button", { name: "Create your first bro" }));

    expect(await screen.findByText(/Copy or share Install \+ connect/)).toBeInTheDocument();
    expect(screen.getByText(/curl -fsSL \.\.\. \| sh -s -- executor run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy install \+ connect/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Copy run-only command/i })).toBeInTheDocument();
  });


  it("creates the first Bro once after connection and shows a done action", async () => {
    let sessionOneSnapshots = 0;
    clientMock.getSessionSnapshot.mockImplementation(async (sessionId: string) => {
      if (sessionId === "session-existing") return forgeSnapshot(sessionId);
      sessionOneSnapshots += 1;
      if (sessionOneSnapshots >= 3) {
        return {
          ...emptySessionSnapshot(sessionId),
          executor_nodes: [
            usableExecutorNode({
              node_id: "node-1",
              name: "Local node",
              last_connected_at: "2026-05-23T20:00:00Z",
            }),
          ],
        };
      }
      return emptySessionSnapshot(sessionId);
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Create your first bro" }));
    fireEvent.click(await screen.findByTestId("bro-setup-create-node"));

    await waitFor(() => expect(clientMock.createPersona).toHaveBeenCalledTimes(1), { timeout: 3500 });
    expect(clientMock.createPersona).toHaveBeenCalledWith("session-1", {
      name: "atlas",
      avatar: "bro",
      base_prompt: "Execute direct typed and push-to-talk instructions in the connected workspace.",
      executor_node_id: "node-1",
    });
    expect(screen.getByTestId("bro-setup-done")).toHaveTextContent("Done");

    await new Promise((resolve) => setTimeout(resolve, 1700));
    expect(clientMock.createPersona).toHaveBeenCalledTimes(1);
  });

  it("resumes a Bro detail session from sid and targets voice to that Bro", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByText("Current draft")).toBeInTheDocument();
    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-existing"));
    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-existing", "forge"));
  });

  it("opens Bro detail from the desktop home card", async () => {
    clientMock.bootstrapPublicUser.mockResolvedValueOnce({
      user: { user_id: "user-1" },
      session_id: "session-existing",
      default_persona_id: "forge",
      default_bro_detail_session_id: "detail-forge",
    });

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("bro-card-forge"));

    await waitFor(() => expect(window.location.pathname).toBe("/bros/forge"));
    expect(screen.getByRole("heading", { name: "Forge" })).toBeInTheDocument();
  });

  it("offers an install-first copy connect command action on home when the bro's node is offline", async () => {
    const offlineNode = usableExecutorNode({
      connected_executors: [],
      connection_status: "disconnected",
      last_connected_at: "2026-05-23T20:00:00Z",
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce(forgeSnapshot("session-existing", offlineNode));
    clientMock.revealExecutorNodeConnectCommand.mockResolvedValueOnce({
      node: offlineNode,
      token: "token-revive",
    });
    window.history.replaceState({}, "", "/?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const copyBtn = await screen.findByTestId("home-bro-copy-command-forge");
    fireEvent.click(copyBtn);

    await waitFor(() => expect(clientMock.revealExecutorNodeConnectCommand).toHaveBeenCalledWith("session-existing", "node-forge"));
    expect(clientMock.buildExecutorConnectCommands).toHaveBeenCalledWith("node-forge", "token-revive", {
      enabledExecutors: ["codex"],
      acpxAgent: null,
    });
    expect(window.location.pathname).toBe("/");
  });

  it("hides the home copy connect command action for connected bros", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(forgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    await screen.findByTestId("bro-card-forge");
    expect(screen.queryByTestId("home-bro-copy-command-forge")).not.toBeInTheDocument();
  });

  it("opens a recent Home thread through the Bro detail route", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_threads = [
      {
        thread_id: "recent-thread-1",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "Recent home thread",
        preview: "Open from home",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-27T22:00:00+00:00",
        diagnostics: { codex_thread_id: "codex-recent-1" },
      },
    ] as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValueOnce(snapshot);
    window.history.replaceState({}, "", "/?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByText("Recent home thread"));

    await waitFor(() => {
      expect(window.location.pathname).toBe("/bros/forge");
      expect(new URLSearchParams(window.location.search).get("thread")).toBe("recent-thread-1");
      expect(clientMock.openBroThread).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        threadId: "recent-thread-1",
      });
    });
  });

  it("sends desktop typed Bro detail input directly to the executor node", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Run the desktop direct send path" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-1",
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "Run the desktop direct send path",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
    expect(clientMock.sendSocketDraftAsrTurn).not.toHaveBeenCalled();
    expect(clientMock.sendDraft).not.toHaveBeenCalled();
  });

  it("routes desktop typed input to the selected Codex thread from the URL", async () => {
    const snapshot = activeForgeSnapshot("session-existing");
    snapshot.tasks.push({
      ...snapshot.tasks[0],
      task_id: "task-old",
      root_task_id: "task-old",
      title: "Older Codex thread",
      goal: "Previous work",
      status: "completed",
      metadata: { persona_id: "forge" },
    });
    snapshot.bro_threads.push({
      thread_id: "exec-old",
      persona_id: "forge",
      persona_name: "Forge",
      executor_id: "codex",
      executor_node_id: "node-forge",
      execution_session_id: "exec-old",
      status: "completed",
      title: "Older Codex thread",
      preview: "Previous work",
      progress: 100,
      task_ids: ["task-old"],
      active_task_id: null,
      latest_task_id: "task-old",
      has_resume_handle: true,
      updated_at: null,
      diagnostics: { codex_thread_id: "codex-thread-old" },
    } as any);
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValueOnce(snapshot);
    clientMock.submitExecutorTextInstruction.mockResolvedValueOnce({
      instruction_id: "txt-old",
      target_persona_id: "forge",
      target_thread_id: "exec-old",
      status: "accepted",
    });
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-old");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Older Codex thread")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "continue the older thread" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-old",
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "continue the older thread",
      });
    });
    expect(window.location.search).toContain("thread=exec-old");
  });

  it("opens a selected imported thread and renders native messages", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_threads = [
      {
        thread_id: "codex-import-history",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "Imported Codex thread",
        preview: "Remote history",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-26T22:00:00+00:00",
        timeline_status: "not_loaded",
        timeline_error: null,
        diagnostics: { codex_thread_id: "codex-native-history" },
      },
    ] as any;
    const importedThread = snapshot.bro_threads[0] as any;
    const hydrated = {
      ...snapshot,
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "codex-import-history",
          userText: "Imported request",
          assistantText: "Fetched history response.",
        }),
      ],
      bro_threads: [
        {
          ...importedThread,
          timeline_status: "loaded",
          timeline_error: null,
        },
      ],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValueOnce(hydrated);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=codex-import-history");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Imported Codex thread")).toBeInTheDocument();
    await waitFor(() => {
      expect(clientMock.openBroThread).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        threadId: "codex-import-history",
      });
    });
    await waitFor(() => {
      expect(screen.getAllByText("Imported request").length).toBeGreaterThanOrEqual(2);
    });
    expect(screen.getAllByText("Imported request").some((node) => node.closest(".dt-status-title"))).toBe(true);
    const response = screen.getByText("Fetched history response.");
    expect(response).toBeInTheDocument();
    expect(response.closest(".dt-status")).not.toBeNull();
    expect(screen.getAllByText("You").length).toBeGreaterThanOrEqual(1);
  });

  it("keeps the latest selected imported thread history when an earlier open resolves late", async () => {
    const snapshot = forgeSnapshot("session-existing");
    const importedThreads = [
      {
        thread_id: "codex-import-first",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "First imported thread",
        preview: "Remote first history",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-26T22:00:00+00:00",
        timeline_status: "not_loaded",
        timeline_error: null,
        diagnostics: { codex_thread_id: "codex-native-first" },
      },
      {
        thread_id: "codex-import-second",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "Second imported thread",
        preview: "Remote second history",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-26T21:00:00+00:00",
        timeline_status: "not_loaded",
        timeline_error: null,
        diagnostics: { codex_thread_id: "codex-native-second" },
      },
    ] as any[];
    (snapshot as any).bro_threads = importedThreads;
    const hydratedFirst = {
      ...snapshot,
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "codex-import-first",
          executor_turn_id: "turn-first",
          assistantText: "First fetched response.",
          updated_at: "2026-05-26T22:02:00+00:00",
        }),
      ],
      bro_threads: [
        { ...importedThreads[0], timeline_status: "loaded", timeline_error: null },
        importedThreads[1],
      ],
    };
    const hydratedSecond = {
      ...snapshot,
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "codex-import-second",
          executor_turn_id: "turn-second",
          assistantText: "Second fetched response.",
          updated_at: "2026-05-26T21:02:00+00:00",
        }),
      ],
      bro_threads: [
        importedThreads[0],
        { ...importedThreads[1], timeline_status: "loaded", timeline_error: null },
      ],
    };
    let resolveFirstOpen: ((value: typeof hydratedFirst) => void) | null = null;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockImplementation(async (_sessionId: string, body: any) => {
      if (body.threadId === "codex-import-first") {
        return await new Promise((resolve) => {
          resolveFirstOpen = resolve;
        });
      }
      return hydratedSecond;
    });
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("First imported thread")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Second imported thread/ }));

    await waitFor(() => {
      expect(clientMock.openBroThread).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        threadId: "codex-import-second",
      });
    });
    expect(await screen.findByText("Second fetched response.")).toBeInTheDocument();

    await act(async () => {
      resolveFirstOpen?.(hydratedFirst);
    });

    expect(screen.getByText("Second fetched response.")).toBeInTheDocument();
    expect(screen.queryByText("First fetched response.")).not.toBeInTheDocument();
  });

  it("pages the desktop thread rail and expands on demand", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_threads = Array.from({ length: 30 }, (_, index) => {
      const number = String(index + 1).padStart(2, "0");
      return {
        thread_id: `thread-${number}`,
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: `Paged thread ${number}`,
        preview: `History ${number}`,
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: `2026-05-26T20:${number}:00+00:00`,
        diagnostics: { codex_thread_id: `codex-${number}` },
      };
    }) as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockResolvedValue(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Paged thread 01")).toBeInTheDocument();
    expect(screen.getByText("Paged thread 25")).toBeInTheDocument();
    expect(screen.queryByText("Paged thread 26")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show 5 more" }));

    expect(await screen.findByText("Paged thread 30")).toBeInTheDocument();
  });

  it("keeps New thread pending until the first desktop send", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-1");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByRole("button", { name: "New thread with Forge" }));
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "start a separate thread" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: null,
        createNewThread: true,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "start a separate thread",
      });
    });
  });

  it("sends New thread desktop PTT audio with new-thread intent and resolves the returned thread", async () => {
    const initial = {
      ...activeForgeSnapshot("session-existing"),
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "exec-1",
          executor_turn_id: "history-1",
          userText: "Existing thread request",
          assistantText: "Existing thread response.",
        }),
      ],
    };
    clientMock.getSessionSnapshot
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce({
        ...initial,
        bro_threads: [
          ...(initial.bro_threads as any[]),
          {
            ...(initial.bro_threads[0] as any),
            thread_id: "thread-new",
            execution_session_id: null,
            status: "queued",
            title: "Fresh audio thread",
            task_ids: ["task-new"],
            active_task_id: "task-new",
            latest_task_id: "task-new",
          },
        ],
        bro_timeline_turns: [],
      });
    clientMock.submitExecutorAudioInstruction.mockResolvedValueOnce({
      audio_instruction_id: "aud-new",
      target_persona_id: "forge",
      target_thread_id: "thread-new",
      status: "accepted",
      duration_ms: 1,
      size_bytes: 32,
      transcript_text: "fresh audio request",
    });
    const track = { stop: vi.fn() };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) },
    });
    class MockMediaRecorder {
      static isTypeSupported = vi.fn(() => true);
      state = "inactive";
      mimeType = "audio/webm;codecs=opus";
      private listeners: Record<string, Array<(event?: any) => void>> = {};

      constructor(_stream: MediaStream, _options: { mimeType: string }) {}

      addEventListener(type: string, listener: (event?: any) => void) {
        this.listeners[type] = [...(this.listeners[type] ?? []), listener];
      }

      start() {
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
        for (const listener of this.listeners.dataavailable ?? []) {
          listener({ data: new Blob([new Uint8Array([0, 0, 1, 0])], { type: this.mimeType }) });
        }
        for (const listener of this.listeners.stop ?? []) listener();
      }
    }
    class MockAudioContext {
      async decodeAudioData(_buffer: ArrayBuffer) {
        return {
          duration: 0.001,
          length: 16,
          numberOfChannels: 1,
          sampleRate: 16000,
          getChannelData: () => new Float32Array(16),
        };
      }

      async close() {}
    }
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=exec-1");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Existing thread response.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New thread with Forge" }));
    expect(await screen.findByText("No messages with Forge yet")).toBeInTheDocument();

    const button = screen.getByTestId("voice-session-start");
    fireEvent.pointerDown(button, { pointerId: 1 });
    await waitFor(() => expect(screen.getByTestId("voice-session-start")).toHaveClass("dt-cmp-mic-free"));
    const recordingButton = screen.getByTestId("voice-session-start");
    fireEvent.pointerUp(recordingButton, { pointerId: 1 });
    fireEvent.keyUp(recordingButton, { key: " " });

    await waitFor(() => {
      expect(clientMock.submitExecutorAudioInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: null,
        createNewThread: true,
        pcm16: expect.any(Blob),
        durationMs: 1,
        sampleRate: 16000,
        numChannels: 1,
        samplesPerChannel: 16,
        clientRequestId: expect.stringMatching(/^audio-/),
      });
    });
    await waitFor(() => expect(window.location.search).toContain("thread=thread-new"));
    expect(screen.queryByText("Existing thread response.")).not.toBeInTheDocument();
    expect(document.querySelector(".nb-audio-transcript")).toHaveTextContent("fresh audio request");
  });

  it("enables desktop typed send for a connected idle Bro", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const input = await screen.findByPlaceholderText("Type to Forge...");
    fireEvent.change(input, { target: { value: "start from idle bro" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: null,
        createNewThread: true,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "start from idle bro",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
  });

  it("does not render conversation replies in the Bro detail timeline", async () => {
    clientMock.getConversationSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      conversation_history: [
        {
          message_id: "msg-overall",
          role: "assistant",
          text: "Conversation reply from Communication Brain",
          created_at: "2026-05-27T00:00:00Z",
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    await waitFor(() => {
      expect(clientMock.getConversationSnapshot).toHaveBeenCalledWith("session-existing");
    });
    expect(screen.queryByText("Conversation reply from Communication Brain")).not.toBeInTheDocument();
  });

  it("keeps desktop typed send enabled for a queued direct Bro task", async () => {
    const snapshot = activeForgeSnapshot("session-existing");
    snapshot.execution_sessions = [];
    snapshot.execution_runs = [];
    snapshot.tasks[0] = {
      ...snapshot.tasks[0],
      status: "queued",
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.closeBroThread.mockResolvedValueOnce(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const input = await screen.findByPlaceholderText("Type to Forge...");
    fireEvent.change(input, { target: { value: "retry queued task" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-1",
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "retry queued task",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
  });

  it("uses the artboarded offline detail state and blocks talk/send for disconnected usable nodes", async () => {
    const offlineNode = usableExecutorNode({
      connected_executors: [],
      connection_status: "disconnected",
      last_connected_at: "2026-05-23T20:00:00Z",
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce(forgeSnapshot("session-existing", offlineNode));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByTestId("bro-node-disconnected-warning")).toHaveTextContent("Workshop Mini is not connected");
    expect(screen.getByTestId("bro-node-copy-command")).toHaveTextContent("Copy install + connect");
    expect(screen.getByTestId("bro-node-copy-run-only-command")).toHaveTextContent("Run-only");
    fireEvent.click(screen.getByTestId("bro-node-copy-command"));
    await waitFor(() => expect(screen.getByText(/install-newbro-cli\.sh/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("bro-node-copy-run-only-command"));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("newbro executor run --node-id node-1 --token token-1"));
    expect(screen.getByTestId("voice-session-start")).toBeDisabled();
    expect(screen.getByPlaceholderText("Reconnect the node before sending")).toBeDisabled();
  });

  it("clears the existing thread history when 'New thread' is clicked on the desktop detail page", async () => {
    const snapshot = {
      ...forgeSnapshot("session-existing"),
      tasks: [
        {
          task_id: "task-history-1",
          root_task_id: "task-history-1",
          parent_task_id: null,
          title: "Previous request",
          goal: "Previous request body",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 0,
          latest_instruction: "Previous request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            bro_thread_id: "thread-existing",
            target_thread_id: "thread-existing",
            source_kind: "codex_thread_history",
          },
        },
      ],
      bro_threads: [
        {
          thread_id: "thread-existing",
          persona_id: "forge",
          persona_name: "Forge",
          executor_id: "codex",
          executor_node_id: "node-forge",
          execution_session_id: "exec-existing",
          status: "completed",
          title: "Previous request",
          preview: "Previous request body",
          progress: 100,
          task_ids: ["task-history-1"],
          active_task_id: null,
          latest_task_id: "task-history-1",
          has_resume_handle: true,
          updated_at: "2026-05-20T12:00:00Z",
          diagnostics: {},
        },
      ],
      summaries: [
        {
          task_id: "task-history-1",
          operational_summary: "Previous response body.",
          conversational_summary: "Previous response body.",
          latest_user_visible_status: "Previous response body.",
          needs_user_input: false,
        },
      ],
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "thread-existing",
          executor_turn_id: "history-1",
          userText: "Previous request",
          assistantText: "Previous response body.",
          created_at: "2026-05-20T12:00:00Z",
          updated_at: "2026-05-20T12:01:00Z",
        }),
      ],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Previous response body.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /New thread with Forge/i }));

    await waitFor(() => expect(screen.queryByText("Previous response body.")).not.toBeInTheDocument());
    expect(screen.getByText("No messages with Forge yet")).toBeInTheDocument();
  });

  it("clears the existing thread history when 'New thread' is clicked on mobile", async () => {
    const snapshot = {
      ...forgeSnapshot("session-existing"),
      bro_threads: [
        {
          thread_id: "thread-existing",
          persona_id: "forge",
          persona_name: "Forge",
          executor_id: "codex",
          executor_node_id: "node-forge",
          execution_session_id: "exec-existing",
          status: "completed",
          title: "Previous request",
          preview: "Previous request body",
          progress: 100,
          task_ids: ["task-history-1"],
          active_task_id: null,
          latest_task_id: "task-history-1",
          has_resume_handle: true,
          updated_at: "2026-05-20T12:00:00Z",
          diagnostics: {},
        },
      ],
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "thread-existing",
          executor_turn_id: "history-1",
          userText: "Previous request",
          assistantText: "Previous response body.",
          created_at: "2026-05-20T12:00:00Z",
          updated_at: "2026-05-20T12:01:00Z",
        }),
      ],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.closeBroThread.mockResolvedValueOnce(snapshot);
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));
    expect(await screen.findByText("Previous response body.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch thread" }));
    fireEvent.click(screen.getByRole("button", { name: /New thread with Forge/i }));

    await waitFor(() => expect(screen.queryByText("Previous response body.")).not.toBeInTheDocument());
    expect(screen.getByText("No messages with Forge yet")).toBeInTheDocument();
    expect(screen.getAllByText("New thread").length).toBeGreaterThan(0);
  });

  it("keeps the freshly resolved new thread selected after the first send", async () => {
    const snapshot = {
      ...forgeSnapshot("session-existing"),
      tasks: [
        {
          task_id: "task-history-1",
          root_task_id: "task-history-1",
          parent_task_id: null,
          title: "Previous request",
          goal: "Previous request body",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 0,
          latest_instruction: "Previous request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            bro_thread_id: "thread-existing",
            target_thread_id: "thread-existing",
            source_kind: "codex_thread_history",
          },
        },
      ],
      bro_threads: [
        {
          thread_id: "thread-existing",
          persona_id: "forge",
          persona_name: "Forge",
          executor_id: "codex",
          executor_node_id: "node-forge",
          execution_session_id: "exec-existing",
          status: "completed",
          title: "Previous request",
          preview: "Previous request body",
          progress: 100,
          task_ids: ["task-history-1"],
          active_task_id: null,
          latest_task_id: "task-history-1",
          has_resume_handle: true,
          updated_at: "2026-05-20T12:00:00Z",
          diagnostics: {},
        },
      ],
      summaries: [
        {
          task_id: "task-history-1",
          operational_summary: "Previous response body.",
          conversational_summary: "Previous response body.",
          latest_user_visible_status: "Previous response body.",
          needs_user_input: false,
        },
      ],
      bro_timeline_turns: [
        timelineTurn({
          thread_id: "thread-existing",
          executor_turn_id: "history-1",
          userText: "Previous request",
          assistantText: "Previous response body.",
          created_at: "2026-05-20T12:00:00Z",
          updated_at: "2026-05-20T12:01:00Z",
        }),
      ],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.submitExecutorTextInstruction.mockResolvedValueOnce({
      instruction_id: "txt-new",
      target_persona_id: "forge",
      target_thread_id: "thread-new",
      status: "accepted",
    });
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Previous response body.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /New thread with Forge/i }));
    expect(await screen.findByText("No messages with Forge yet")).toBeInTheDocument();

    clientMock.openBroThread.mockClear();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "kickoff" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", expect.objectContaining({
        createNewThread: true,
        text: "kickoff",
      })),
    );
    expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(window.location.search).toContain("thread=thread-new"));
    expect(screen.queryByText("No messages with Forge yet")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const openedAfterSubmit = clientMock.openBroThread.mock.calls.map(([, body]: any[]) => body.threadId);
    expect(openedAfterSubmit).not.toContain("thread-existing");
    expect(openedAfterSubmit).not.toContain("thread-new");
  });

  it("shows thread history loading instead of the empty state", async () => {
    const snapshot = forgeSnapshot("session-existing");
    snapshot.bro_threads = [
      {
        thread_id: "codex-import-loading",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "Loading imported thread",
        preview: "Remote history",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-26T22:00:00+00:00",
        timeline_status: "loading",
        timeline_error: null,
        diagnostics: { codex_thread_id: "codex-native-loading" },
      },
    ] as any;
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    clientMock.openBroThread.mockImplementation(() => new Promise(() => undefined));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing&thread=codex-import-loading");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Fetching thread history…")).toBeInTheDocument();
    expect(screen.queryByText("No messages with Forge yet")).not.toBeInTheDocument();
  });

  it("enables desktop PTT audio for a connected idle Codex Bro", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeEnabled();
    expect(screen.getByTestId("voice-session-start")).toHaveAccessibleName("Hold to record audio");
    expect(connectorMock.prepareConnectorSession).not.toHaveBeenCalled();
  });

  it("enables desktop PTT audio when the Bro has an active Codex execution session", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeEnabled();
    expect(screen.getByTestId("voice-session-start")).toHaveAccessibleName("Hold to record audio");
  });

  it("enables desktop PTT audio for a continuation run on the Bro's current task", async () => {
    const snapshot = activeForgeSnapshot("session-existing");
    snapshot.execution_sessions[0] = {
      ...snapshot.execution_sessions[0],
      task_id: "task-previous",
      run_ids: ["run-previous", "run-1"],
    };
    clientMock.getSessionSnapshot.mockResolvedValueOnce(snapshot);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeEnabled();
    expect(screen.getByTestId("voice-session-start")).toHaveAccessibleName("Hold to record audio");
  });

  it("sends desktop PTT text directly to the executor node", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const input = await screen.findByPlaceholderText("Type to Forge...");
    fireEvent.change(input, { target: { value: "continue directly" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-1",
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "continue directly",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
  });

  it("reconciles desktop PTT audio with the canonical timeline without duplicate bubbles", async () => {
    const initial = activeForgeSnapshot("session-existing");
    const canonical = {
      ...activeForgeSnapshot("session-existing"),
      bro_timeline_turns: [
        {
          turn_id: "exec-1:newbro:audio-client-1",
          thread_id: "exec-1",
          persona_id: "forge",
          executor_id: "codex",
          owner: "newbro",
          client_request_id: "audio-client-1",
          executor_thread_id: "codex-thread-1",
          executor_turn_id: "turn-1",
          input_modality: "audio",
          user: {
            message_id: "task-audio:user",
            role: "user",
            kind: "audio",
            text: null,
            transcript: "hello from audio",
            audio_id: "aud-1",
            duration_ms: 1000,
            created_at: "2026-05-26T22:01:00+00:00",
            updated_at: "2026-05-26T22:01:00+00:00",
            status: "sent",
            metadata: {},
          },
          assistant: {
            message_id: "task-audio:assistant",
            role: "assistant",
            kind: "text",
            text: "Task-backed response.",
            transcript: null,
            audio_id: null,
            duration_ms: null,
            created_at: "2026-05-26T22:01:04+00:00",
            updated_at: "2026-05-26T22:01:04+00:00",
            status: "completed",
            metadata: {},
          },
          task: null,
          status: "completed",
          created_at: "2026-05-26T22:01:00+00:00",
          updated_at: "2026-05-26T22:01:04+00:00",
          metadata: {},
        },
      ],
    } as any;
    clientMock.getSessionSnapshot
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(canonical);
    clientMock.submitExecutorAudioInstruction.mockImplementationOnce(async (_sessionId: string, payload: any) => {
      canonical.bro_timeline_turns[0].client_request_id = payload.clientRequestId;
      canonical.bro_timeline_turns[0].turn_id = `exec-1:newbro:${payload.clientRequestId}`;
      return {
        audio_instruction_id: "aud-1",
        target_persona_id: "forge",
        target_thread_id: "exec-1",
        status: "accepted",
        duration_ms: 1000,
        size_bytes: 32,
        transcript_text: "hello from audio",
      };
    });
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: vi.fn(),
    });
    const track = { stop: vi.fn() };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) },
    });
    class MockMediaRecorder {
      static isTypeSupported = vi.fn(() => true);
      state = "inactive";
      mimeType = "audio/webm;codecs=opus";
      private listeners: Record<string, Array<(event?: any) => void>> = {};

      constructor(_stream: MediaStream, _options: { mimeType: string }) {}

      addEventListener(type: string, listener: (event?: any) => void) {
        this.listeners[type] = [...(this.listeners[type] ?? []), listener];
      }

      start() {
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
        for (const listener of this.listeners.dataavailable ?? []) {
          listener({ data: new Blob([new Uint8Array([0, 0, 1, 0])], { type: this.mimeType }) });
        }
        for (const listener of this.listeners.stop ?? []) {
          listener();
        }
      }
    }
    class MockAudioContext {
      async decodeAudioData(_buffer: ArrayBuffer) {
        return {
          duration: 0.001,
          length: 16,
          numberOfChannels: 1,
          sampleRate: 16000,
          getChannelData: () => new Float32Array(16),
        };
      }

      async close() {}
    }
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const button = await screen.findByTestId("voice-session-start");
    fireEvent.pointerDown(button, { pointerId: 1 });
    await waitFor(() => expect(screen.getByTestId("voice-session-start")).toHaveClass("dt-cmp-mic-free"));
    const recordingButton = screen.getByTestId("voice-session-start");
    fireEvent.pointerUp(recordingButton, { pointerId: 1 });
    fireEvent.keyUp(recordingButton, { key: " " });

    await waitFor(() => {
      expect(clientMock.submitExecutorAudioInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-1",
        createNewThread: false,
        pcm16: expect.any(Blob),
        durationMs: 1,
        sampleRate: 16000,
        numChannels: 1,
        samplesPerChannel: 16,
        clientRequestId: expect.stringMatching(/^audio-/),
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText("Voice note")).toHaveLength(1);
      expect(document.querySelectorAll(".nb-audio-transcript")).toHaveLength(1);
      expect(document.querySelector(".nb-audio-transcript")).toHaveTextContent("hello from audio");
      expect(screen.getAllByText("Task-backed response.")).toHaveLength(1);
    });
  });

  it("keeps desktop PTT audio disabled when connected Codex does not advertise audio support", async () => {
    const unsupportedNode = usableExecutorNode({
      connected_executor_capabilities: [
        {
          executor_type: "codex",
          supports_resume: true,
          supports_follow_up: true,
          supports_audio_instruction: false,
          supports_pause: true,
          supports_cancel: true,
        },
      ],
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing", unsupportedNode));
    clientMock.openBroThread.mockResolvedValueOnce(activeForgeSnapshot("session-existing", unsupportedNode));
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeDisabled();
    expect(screen.getByTestId("voice-session-start")).toHaveAccessibleName(
      "Enable local Whisper on the executor node before recording.",
    );
  });

  it("sends mobile thread text directly to the executor node", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce(activeForgeSnapshot("session-existing"));
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));
    fireEvent.change(await screen.findByLabelText("Message"), {
      target: { value: "Please draft the launch note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(clientMock.submitExecutorTextInstruction).toHaveBeenCalledWith("session-existing", {
        targetPersonaId: "forge",
        targetThreadId: "exec-1",
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "Please draft the launch note",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
    expect(clientMock.sendSocketDraftAsrTurn).not.toHaveBeenCalled();
  });

  it("starts selected mobile voice through the connector path", async () => {
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(screen.queryByRole("button", { name: "Call NewBro" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));
    fireEvent.click(await screen.findByRole("tab", { name: /Always on/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Wake up Forge" }));

    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-existing", "forge"));
    await waitFor(() => expect(connectorMock.prepareConnectorSession).toHaveBeenCalledWith({
      synapse_session_id: "session-existing",
    }));
  });

  it("renders removed standalone management routes as blank", async () => {
    window.history.replaceState({}, "", "/nodes?sid=session-existing");
    const { container } = render(<RouterProvider router={getRouter()} />);

    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(container).not.toHaveTextContent("Nodes");
    expect(container).not.toHaveTextContent("Settings");
    expect(container).not.toHaveTextContent("Unable to reach the Newbro API");
    expect(container).not.toHaveTextContent("not found");
  });
});

describe("buildBroCardModels", () => {
  it("keeps an empty runtime persona list empty", () => {
    expect(buildBroCardModels([], [], [], [], [])).toEqual([]);
  });

  it("maps runtime personas into live bro cards", () => {
    const cards = buildBroCardModels(
      [
        {
          persona_id: "forge",
          name: "Forge",
          avatar: "bro",
          executor_node_id: "node-forge",
          bro_detail_session_id: "bro-detail-forge",
          status: "idle",
          current_task_id: null,
        },
      ],
      [usableExecutorNode() as any],
      [],
      [],
      [],
    );

    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      id: "forge",
      name: "Forge",
      source: "runtime",
      liveState: "live",
    });
  });
});

describe("buildBroTaskRecords", () => {
  it("keeps active Bro progress in chronological order so latest renders last", () => {
    const records = buildBroTaskRecords("forge", {
      activeTaskId: "task-active",
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-old",
          root_task_id: "task-old",
          parent_task_id: null,
          title: "Previous task",
          goal: "Previous work",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            updated_at: "2026-05-27T08:00:00Z",
          },
        },
        {
          task_id: "task-active",
          root_task_id: "task-active",
          parent_task_id: null,
          title: "Active task",
          goal: "Current work",
          status: "running",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            updated_at: "2026-05-27T09:00:00Z",
          },
        },
      ],
      executionRuns: [
        {
          run_id: "run-active",
          task_id: "task-active",
          execution_session_id: "exec-active",
          executor_type: "codex",
          status: "running",
          claimed_by: null,
          run_revision: 1,
          latest_progress_message: "Checking files now.",
          output_summary: null,
          block_reason: null,
          failure_reason: null,
          metadata: {},
        },
      ],
      summaries: [],
    });

    expect(records.map((record) => record.taskId)).toEqual(["task-old", "task-active"]);
    expect(records.at(-1)).toMatchObject({
      taskId: "task-active",
      status: "running",
      progress: 60,
      description: "Checking files now.",
    });
  });

  it("marks completed Bro task records at full progress", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-done",
          root_task_id: "task-done",
          parent_task_id: null,
          title: "Completed task",
          goal: "Done work",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: { persona_id: "forge", bro_detail_session_id: "detail-forge" },
        },
      ],
      executionRuns: [],
      summaries: [],
    });

    expect(records[0]).toMatchObject({
      taskId: "task-done",
      status: "completed",
      statusLabel: "completed",
      progress: 100,
    });
  });

  it("projects task goals and Codex plans separately from progress", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-plan",
          root_task_id: "task-plan",
          parent_task_id: null,
          title: "Plan task",
          goal: "Display Codex plan",
          status: "running",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: { persona_id: "forge", bro_detail_session_id: "detail-forge" },
        },
      ],
      executionRuns: [
        {
          run_id: "run-plan",
          task_id: "task-plan",
          execution_session_id: "exec-plan",
          executor_type: "codex",
          status: "running",
          claimed_by: null,
          run_revision: 1,
          latest_progress_message: "Checking files.",
          output_summary: null,
          block_reason: null,
          failure_reason: null,
          metadata: {
            latest_plan_event: {
              source: "codex",
              codex_plan: {
                explanation: "Implementation plan",
                steps: [
                  { step: "Read files", status: "completed" },
                  { step: "Patch projection", status: "inProgress" },
                ],
              },
            },
          },
        },
      ],
      summaries: [],
    });

    expect(records[0]).toMatchObject({
      taskId: "task-plan",
      goal: "Display Codex plan",
      description: "Checking files.",
      plan: {
        explanation: "Implementation plan",
        steps: [
          { step: "Read files", status: "completed" },
          { step: "Patch projection", status: "inProgress" },
        ],
      },
    });
  });

  it("does not render assistant-only imported Codex history as a synced user message", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-assistant-history",
          root_task_id: "task-assistant-history",
          parent_task_id: null,
          title: "Assistant-only answer",
          goal: "Assistant-only answer",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            source_kind: "codex_thread_history",
          },
        },
      ],
      executionRuns: [],
      summaries: [
        {
          task_id: "task-assistant-history",
          operational_summary: "Assistant response from imported history.",
          conversational_summary: "Assistant response from imported history.",
          latest_user_visible_status: "Assistant response from imported history.",
          needs_user_input: false,
        },
      ],
    });

    expect(records[0]).toMatchObject({
      taskId: "task-assistant-history",
      description: "Assistant response from imported history.",
    });
    expect(records[0].userText).toBeUndefined();
  });

  it("keeps direct Bro detail text visible as a synced user message", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-direct-text",
          root_task_id: "task-direct-text",
          parent_task_id: null,
          title: "Direct user request",
          goal: "Direct user request",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: null,
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            source_kind: "bro_detail_text",
          },
        },
      ],
      executionRuns: [],
      summaries: [],
    });

    expect(records[0].userText).toBe("Direct user request");
  });

  it("does not show executor persona guidance as direct Bro detail user text", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      tasks: [
        {
          task_id: "task-direct-text",
          root_task_id: "task-direct-text",
          parent_task_id: null,
          title: "Hello, hello",
          goal: "Hello, hello",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: "Execute direct typed and push-to-talk instructions in the connected workspace.\n\nHello, hello",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            source_kind: "bro_detail_ptt",
          },
        },
      ],
      executionRuns: [],
      summaries: [],
    });

    expect(records[0].userText).toBe("Hello, hello");
  });

  it("filters selected thread tasks before applying the timeline limit", () => {
    const records = buildBroTaskRecords("forge", {
      broDetailSessionId: "detail-forge",
      taskIds: ["task-selected-old"],
      limit: 1,
      tasks: [
        {
          task_id: "task-selected-old",
          root_task_id: "task-selected-old",
          parent_task_id: null,
          title: "Older selected request",
          goal: "Older selected request",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: "Older selected request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            source_kind: "codex_thread_history",
          },
        },
        {
          task_id: "task-other-new",
          root_task_id: "task-other-new",
          parent_task_id: null,
          title: "Newer other thread",
          goal: "Newer other thread",
          status: "completed",
          priority: 0,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: null,
          task_revision: 1,
          latest_instruction: "Newer other thread",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            source_kind: "codex_thread_history",
          },
        },
      ],
      executionRuns: [],
      summaries: [],
    });

    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      taskId: "task-selected-old",
      userText: "Older selected request",
    });
  });
});

describe("buildBroThreadRecords", () => {
  it("maps runtime Codex thread projection into selectable thread records", () => {
    const records = buildBroThreadRecords("forge", [
      {
        thread_id: "bro-thread-1",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: "exec-1",
        status: "completed",
        title: "Existing thread",
        preview: "Done already",
        progress: 100,
        task_ids: ["task-1", "task-2"],
        active_task_id: null,
        latest_task_id: "task-2",
        has_resume_handle: true,
        updated_at: null,
        timeline_status: "not_loaded",
        timeline_error: null,
        diagnostics: { codex_thread_id: "codex-thread-1" },
      },
    ]);

    expect(records).toEqual([
      expect.objectContaining({
        threadId: "bro-thread-1",
        title: "Existing thread",
        statusLabel: "completed",
        taskIds: ["task-1", "task-2"],
        hasResumeHandle: true,
      }),
    ]);
  });

  it("maps imported Codex threads without task history", () => {
    const records = buildBroThreadRecords("forge", [
      {
        thread_id: "codex-import-abc123",
        persona_id: "forge",
        persona_name: "Forge",
        executor_id: "codex",
        executor_node_id: "node-forge",
        execution_session_id: null,
        status: "completed",
        title: "Imported outside Newbro",
        preview: "Task: Imported outside Newbro",
        progress: 100,
        task_ids: [],
        active_task_id: null,
        latest_task_id: null,
        has_resume_handle: true,
        updated_at: "2026-05-26T22:00:00+00:00",
        timeline_status: "not_loaded",
        timeline_error: null,
        diagnostics: {
          codex_thread_id: "019e67f5-2e79-77c1-8334-5b04b8c81432",
          imported_from_codex_thread_list: true,
        },
      },
    ]);

    expect(records).toEqual([
      expect.objectContaining({
        threadId: "codex-import-abc123",
        title: "Imported outside Newbro",
        taskIds: [],
        hasResumeHandle: true,
      }),
    ]);
  });
});
