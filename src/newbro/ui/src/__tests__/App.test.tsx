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
  buildExecutorRunCommand: vi.fn(() => "newbro executor run --node-id node-1 --token token-1"),
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
    personas: [],
    interaction_requests: [],
    attention_items: [],
    executor_capabilities: [],
    executor_nodes: [],
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
    expect(await screen.findByText(/newbro executor run/)).toBeInTheDocument();
    expect(screen.getByText(/The Bro appears after the first successful connection/)).toBeInTheDocument();
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

  it("opens a selected imported thread and renders fetched history", async () => {
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
        diagnostics: { codex_thread_id: "codex-native-history" },
      },
    ] as any;
    const importedThread = snapshot.bro_threads[0] as any;
    const hydrated = {
      ...snapshot,
      tasks: [
        {
          task_id: "task-history",
          root_task_id: "task-history",
          parent_task_id: null,
          title: "Imported request",
          goal: "Imported request",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "/tmp/elsewhere",
          task_revision: 0,
          latest_instruction: "Imported request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            bro_thread_id: "codex-import-history",
            target_thread_id: "codex-import-history",
            source_kind: "codex_thread_history",
          },
        },
      ],
      bro_threads: [
        {
          ...importedThread,
          task_ids: ["task-history"],
          latest_task_id: "task-history",
          diagnostics: { codex_thread_id: "codex-native-history", history_hydrated: true },
        },
      ],
      summaries: [
        {
          task_id: "task-history",
          operational_summary: "Fetched history response.",
          conversational_summary: "Fetched history response.",
          latest_user_visible_status: "Fetched history response.",
          needs_user_input: false,
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
    expect(screen.getByText("Fetched history response.")).toBeInTheDocument();
    expect(screen.getAllByText("Sent").length).toBeGreaterThanOrEqual(1);
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
        diagnostics: { codex_thread_id: "codex-native-second" },
      },
    ] as any[];
    (snapshot as any).bro_threads = importedThreads;
    const hydratedFirst = {
      ...snapshot,
      tasks: [
        {
          task_id: "task-history-first",
          root_task_id: "task-history-first",
          parent_task_id: null,
          title: "First imported request",
          goal: "First imported request",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "/tmp/first",
          task_revision: 0,
          latest_instruction: "First imported request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            bro_thread_id: "codex-import-first",
            target_thread_id: "codex-import-first",
            source_kind: "codex_thread_history",
          },
        },
      ],
      bro_threads: [
        { ...importedThreads[0], task_ids: ["task-history-first"], latest_task_id: "task-history-first" },
        importedThreads[1],
      ],
      summaries: [
        {
          task_id: "task-history-first",
          operational_summary: "First fetched response.",
          conversational_summary: "First fetched response.",
          latest_user_visible_status: "First fetched response.",
          needs_user_input: false,
        },
      ],
    };
    const hydratedSecond = {
      ...snapshot,
      tasks: [
        {
          task_id: "task-history-second",
          root_task_id: "task-history-second",
          parent_task_id: null,
          title: "Second imported request",
          goal: "Second imported request",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "/tmp/second",
          task_revision: 0,
          latest_instruction: "Second imported request",
          metadata: {
            persona_id: "forge",
            bro_detail_session_id: "detail-forge",
            bro_thread_id: "codex-import-second",
            target_thread_id: "codex-import-second",
            source_kind: "codex_thread_history",
          },
        },
      ],
      bro_threads: [
        importedThreads[0],
        { ...importedThreads[1], task_ids: ["task-history-second"], latest_task_id: "task-history-second" },
      ],
      summaries: [
        {
          task_id: "task-history-second",
          operational_summary: "Second fetched response.",
          conversational_summary: "Second fetched response.",
          latest_user_visible_status: "Second fetched response.",
          needs_user_input: false,
        },
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
        createNewThread: false,
        clientRequestId: expect.stringMatching(/^text-/),
        text: "start from idle bro",
      });
    });
    expect(clientMock.sendSocketMessage).not.toHaveBeenCalled();
  });

  it("renders conversation replies in the unified Bro detail thread", async () => {
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
    expect(await screen.findByText("Conversation reply from Communication Brain")).toBeInTheDocument();
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
    expect(screen.getByTestId("voice-session-start")).toBeDisabled();
    expect(screen.getByPlaceholderText("Reconnect the node before sending")).toBeDisabled();
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
