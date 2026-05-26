import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider } from "@tanstack/react-router";
import App from "../App";
import { buildBroCardModels } from "../components/newbro";
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
  openSessionStream: vi.fn((_sessionId: string, handlers: any) => {
    socketHarness.handlers = handlers;
    return socketHarness.socket as any;
  }),
  sendSocketMessage: vi.fn(),
  sendSocketDraftAsrTurn: vi.fn(),
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
        status: "idle",
        current_task_id: null,
      },
    ],
    executor_nodes: [node],
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
      base_prompt: "Help turn voice instructions into clear executable drafts.",
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
    expect(screen.getByRole("button", { name: "Hold to Talk" })).toBeDisabled();
    expect(screen.getByPlaceholderText("Reconnect the node before sending")).toBeDisabled();
  });

  it("sends mobile thread text through the shell socket", async () => {
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));
    fireEvent.change(await screen.findByLabelText("Message"), {
      target: { value: "Please draft the launch note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(clientMock.sendSocketMessage).toHaveBeenCalled());
    expect(clientMock.sendSocketMessage.mock.calls.at(-1)?.[2]).toBe("Please draft the launch note");
  });

  it("starts free-route and selected mobile voice through the connector path", async () => {
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Call NewBro" }));
    await waitFor(() => expect(clientMock.clearVoiceTarget).toHaveBeenCalledWith("session-existing"));
    await waitFor(() => expect(connectorMock.prepareConnectorSession).toHaveBeenCalledWith({
      synapse_session_id: "session-existing",
    }));
    await waitFor(() => expect(connectorMock.activateConnectorSession).toHaveBeenCalled());

    connectorMock.prepareConnectorSession.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: "Stop voice session" }));
    await waitFor(() => expect(clientMock.clearVoiceTarget).toHaveBeenCalledTimes(2));
    fireEvent.click(await screen.findByTestId("mobile-bro-row-forge"));
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
