import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider } from "@tanstack/react-router";
import React from "react";
import App from "../App";
import { buildBroCardModels } from "../components/newbro";
import { getRouter } from "../router";

const voiceHarness = vi.hoisted(() => {
  const state = {
    voiceEvents: {} as Record<string, (...args: any[]) => void>,
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
      on: vi.fn((event: string, callback: (...args: any[]) => void) => {
        state.voiceEvents[event] = callback;
      }),
      subscribeMessage: vi.fn(),
      unsubscribe: vi.fn(),
      destroy: vi.fn(),
    },
    reset() {
      state.voiceEvents = {};
      state.rtcClient.on.mockClear();
      state.rtcClient.subscribe.mockClear();
      state.rtcClient.join.mockClear();
      state.rtcClient.publish.mockClear();
      state.rtcClient.leave.mockClear();
      state.micTrack.stop.mockClear();
      state.micTrack.close.mockClear();
      state.micTrack.setEnabled.mockClear();
      state.micTrack.setMuted.mockClear();
      state.rtmClient.login.mockClear();
      state.rtmClient.subscribe.mockClear();
      state.rtmClient.logout.mockClear();
      state.voiceAi.on.mockClear();
      state.voiceAi.subscribeMessage.mockClear();
      state.voiceAi.unsubscribe.mockClear();
      state.voiceAi.destroy.mockClear();
    },
  };
  return state;
});

const socketHarness = vi.hoisted(() => {
  const state = {
    handlers: null as
      | {
          onOpen: () => void;
          onMessage: (event: any) => void;
          onClose: () => void;
          onError: () => void;
        }
      | null,
    socket: {
      readyState: 1,
      close: vi.fn(),
    },
    emitMessage(event: any) {
      state.handlers?.onMessage(event);
    },
    reset() {
      state.handlers = null;
      state.socket.close.mockClear();
    },
  };
  return state;
});

const clientMock = vi.hoisted(() => ({
  createSession: vi.fn(),
  bootstrapPublicUser: vi.fn(),
  redeemInvite: vi.fn(),
  signupPublicUser: vi.fn(),
  getCurrentUser: vi.fn(),
  logoutPublicUser: vi.fn(),
  getSessionSnapshot: vi.fn(),
  getConversationSnapshot: vi.fn(async (sessionId: string) => ({
    session_id: sessionId,
    conversation_history: [],
  })),
  openSessionStream: vi.fn((_sessionId: string, handlers: any) => {
    socketHarness.handlers = handlers;
    return socketHarness.socket as any;
  }),
  sendSocketMessage: vi.fn(),
  submitAgoraVoiceEvent: vi.fn(async (_sessionId: string, event: any) => {
    if (event?.type !== "stt.final") return;
    Promise.resolve().then(() => {
      socketHarness.emitMessage({
        type: "snapshot",
        sequence: 20,
        snapshot: {
          session_id: _sessionId,
          tasks: [],
          execution_sessions: [],
          execution_runs: [],
          execution_modes: [],
          bindings: [],
          summaries: [],
          notification_candidates: [],
          personas: [
            {
              persona_id: event.target_persona_id ?? "forge",
              name: "Forge",
              avatar: "rocket",
              base_prompt: "",
              executor_node_id: "node-forge",
              bro_detail_session_id: "bro-detail-forge",
              status: "idle",
              current_task_id: null,
            },
          ],
          interaction_requests: [],
          attention_items: [],
          executor_capabilities: [],
          executor_nodes: [
            {
              node_id: "node-forge",
              name: "Workshop Mini",
              enabled_executors: ["codex"],
              connected_executors: ["codex"],
              connection_status: "connected",
              token_hint: "tok...1111",
              last_connected_at: null,
              last_seen_at: null,
              acpx_agent: null,
            },
          ],
          draft_session: {
            id: "draft-session-1",
            current_revision_id: "draft-rev-1",
            status: "ready",
            current_draft: {
              text: "Design a polished landing page with a calm hero section.",
              revision_id: "draft-rev-1",
              last_update_summary: "Created a first draft from voice input.",
            },
          },
        },
      });
    });
  }),
  sendSocketDraftAsrTurn: vi.fn((_socket: WebSocket, requestId: string) => {
    Promise.resolve().then(() => {
      socketHarness.emitMessage({
        type: "draft_output_started",
        sequence: 10,
        request_id: requestId,
      });
      socketHarness.emitMessage({
        type: "draft_output_delta",
        sequence: 11,
        request_id: requestId,
        delta: "Design a polished ",
      });
      socketHarness.emitMessage({
        type: "draft_output_delta",
        sequence: 12,
        request_id: requestId,
        delta: "landing page with a calm hero section.",
      });
      socketHarness.emitMessage({
        type: "draft_output_completed",
        sequence: 13,
        request_id: requestId,
        draft_session_id: "draft-session-1",
        draft_text: "Design a polished landing page with a calm hero section.",
      });
    });
  }),
  createPersona: vi.fn(),
  updatePersona: vi.fn(),
  deletePersona: vi.fn(),
  listPersonas: vi.fn(async () => []),
  listExecutorNodes: vi.fn(async () => []),
  createExecutorNode: vi.fn(),
  updateExecutorNode: vi.fn(),
  rotateExecutorNodeCredentials: vi.fn(),
  revealExecutorNodeConnectCommand: vi.fn(),
  deleteExecutorNode: vi.fn(),
  buildExecutorRunCommand: vi.fn(() => "newbro executor run --base-url 'http://localhost:8000' --node-id 'node-1' --token 'token-1'"),
  sendDraft: vi.fn(async () => ({
    task_id: "task-1",
    draft_session_id: "draft-session-1",
    draft_snapshot_id: "draft-snap-1",
  })),
  clearDraft: vi.fn(async () => ({ status: "cleared" })),
  setVoiceTarget: vi.fn(async () => undefined),
  clearVoiceTarget: vi.fn(async () => undefined),
  submitTaskCommand: vi.fn(async () => ({
    command_id: "cmd-1",
    status: "accepted",
    affected_task_ids: ["task-active"],
  })),
  submitDraftAsrTurn: vi.fn(async () => ({
    id: "draft-session-1",
    assigned_bro_id: "forge",
    status: "ready",
    current_draft: {
      text: "Design a polished landing page with a calm hero section.",
      last_update_summary: "Created a first draft from voice input.",
    },
  })),
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
    agent: {
      uid: "9001",
    },
    agent_rtm_uid: "9001-voice-room",
    enable_string_uid: false,
    profile: "VOICE",
    display_name: "Newbro Tester",
    diagnostics: {
      convoai_area: "US",
      selected_url: "https://agora.example.com",
      runtime_session_id: null,
      asr_vendor: "deepgram",
      asr_credential_mode: "managed",
      asr_model: "nova-3",
      tts_vendor: "minimax",
      tts_credential_mode: "managed",
      tts_model: "speech_2_6_turbo",
      agent_uid: "9001",
      agent_rtm_uid: "9001-voice-room",
      rtc_uid: 101,
      rtm_user_id: "101-voice-room",
      enable_string_uid: false,
      enable_rtm: true,
      data_channel: "rtm",
      enable_metrics: true,
      enable_error_message: true,
    },
  })),
  activateConnectorSession: vi.fn(async () => ({
    prepared_session_id: "prepared-1",
    binding_id: "binding-1",
    synapse_session_id: "session-1",
    runtime_session_id: "runtime-1",
    chat_completions_url: "https://gateway.example.com/chat",
    app_id: "agora-app",
    channel_name: "voice-room",
    token: "voice-token",
    uid: 101,
    user_rtm_uid: "101-voice-room",
    agent: {
      uid: "9001",
    },
    agent_rtm_uid: "9001-voice-room",
    enable_string_uid: false,
    profile: "VOICE",
    display_name: "Newbro Tester",
    diagnostics: {
      convoai_area: "US",
      selected_url: "https://agora.example.com",
      runtime_session_id: "runtime-1",
      asr_vendor: "deepgram",
      asr_credential_mode: "managed",
      asr_model: "nova-3",
      tts_vendor: "minimax",
      tts_credential_mode: "managed",
      tts_model: "speech_2_6_turbo",
      agent_uid: "9001",
      agent_rtm_uid: "9001-voice-room",
      rtc_uid: 101,
      rtm_user_id: "101-voice-room",
      enable_string_uid: false,
      enable_rtm: true,
      data_channel: "rtm",
      enable_metrics: true,
      enable_error_message: true,
    },
  })),
  stopConnectorSessionBeacon: vi.fn(() => true),
  prepareSttSession: vi.fn(async () => ({
    prepared_stt_session_id: "prepared-stt-1",
    app_id: "agora-app",
    channel_name: "nbstt-session-bro-random",
    token: "stt-token",
    uid: 101,
    status: "prepared",
  })),
  startSttSession: vi.fn(async () => ({
    stt_session_id: "stt-1",
    app_id: "agora-app",
    channel_name: "nbstt-session-bro-random",
    token: "stt-token",
    uid: 101,
    pub_bot_uid: 100101,
    sub_bot_uid: 100102,
    agent_id: "agent-1",
    status: "started",
    languages: ["zh-CN", "en-US"],
    subscribe_audio_uids: ["101"],
  })),
  heartbeatSttSession: vi.fn(async () => ({ status: "active" })),
  querySttSession: vi.fn(async () => ({
    stt_session_id: "stt-1",
    agent_id: "agent-1",
    status: "running",
    raw: {},
  })),
  leaveSttSession: vi.fn(async () => {}),
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
    TranscriptHelperMode: {
      AUTO: "AUTO",
    },
  })),
  teardownVoiceSession: vi.fn(async () => {}),
}));

vi.mock("../lib/session-client", () => clientMock);
vi.mock("../lib/connector-client", () => connectorMock);
vi.mock("../lib/voice-runtime", () => runtimeMock);

function submittedSttFinalEvents() {
  return clientMock.submitAgoraVoiceEvent.mock.calls.filter(([, event]: any[]) => event?.type === "stt.final");
}

function submittedSttPartialEvents() {
  return clientMock.submitAgoraVoiceEvent.mock.calls.filter(([, event]: any[]) => event?.type === "stt.partial");
}

function expectLastSttFinal(text: string, targetPersonaId = "forge") {
  expect(clientMock.submitAgoraVoiceEvent).toHaveBeenLastCalledWith("session-existing", expect.objectContaining({
    session_id: "session-existing",
    type: "stt.final",
    text,
    target_persona_id: targetPersonaId,
  }));
}

describe("Newbro voice shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    voiceHarness.reset();
    socketHarness.reset();
    window.history.replaceState({}, "", "/");
    clientMock.createSession.mockResolvedValue({ session_id: "session-1" });
    clientMock.bootstrapPublicUser.mockResolvedValue({
      user: { user_id: "user-1" },
      session_id: "session-1",
      default_persona_id: null,
      default_bro_detail_session_id: null,
    });
    clientMock.redeemInvite.mockResolvedValue({ user: { user_id: "user-1" } });
    clientMock.signupPublicUser.mockResolvedValue({ user: { user_id: "user-1", email: "user@example.com" } });
    clientMock.getCurrentUser.mockResolvedValue({ user: { user_id: "user-1" } });
    clientMock.logoutPublicUser.mockResolvedValue({ ok: true });
    clientMock.getSessionSnapshot.mockImplementation(async (sessionId: string) => ({
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
    }));
    clientMock.getConversationSnapshot.mockImplementation(async (sessionId: string) => ({
      session_id: sessionId,
      conversation_history: [],
    }));
    clientMock.createExecutorNode.mockResolvedValue({
      node: {
        node_id: "node-1",
        name: "Local node",
        enabled_executors: ["codex"],
        connected_executors: [],
        connection_status: "disconnected",
        token_hint: "tok...0001",
        last_connected_at: null,
        last_seen_at: null,
        acpx_agent: null,
      },
      token: "token-1",
    });
    clientMock.revealExecutorNodeConnectCommand.mockResolvedValue({
      node: {
        node_id: "node-1",
        name: "Local node",
        enabled_executors: ["codex"],
        connected_executors: [],
        connection_status: "disconnected",
        token_hint: "tok...0001",
        last_connected_at: null,
        last_seen_at: null,
        acpx_agent: null,
      },
      token: "token-1",
    });
    clientMock.updatePersona.mockResolvedValue({});
  });

  it("boots into an explicit empty interaction-memory state", async () => {
    render(<App />);

    expect(await screen.findByTestId("bros-panel")).toBeInTheDocument();
    expect(screen.queryByText("COMMAND CENTER")).not.toBeInTheDocument();
    expect(screen.queryByText("Transcript will appear here.")).not.toBeInTheDocument();
    expect(screen.queryByTestId("voice-session-start")).not.toBeInTheDocument();
    expect(screen.queryByTestId("voice-session-stop")).not.toBeInTheDocument();
    expect(screen.queryByTestId("voice-session-mic-toggle")).not.toBeInTheDocument();
    expect(screen.queryByText("No transcript yet")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Start a live session to fill this memory with real transcript turns."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("No live session yet. Press Start in the top bar to begin voice interaction."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Atlas")).toBeInTheDocument();

    await waitFor(() => expect(clientMock.bootstrapPublicUser).toHaveBeenCalled());
    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-1"));
    expect(window.location.search).toBe("?sid=session-1");
  });

  it("boots invited users directly into their default Bro detail", async () => {
    clientMock.bootstrapPublicUser.mockResolvedValueOnce({
      user: { user_id: "user-1" },
      session_id: "session-1",
      default_persona_id: "atlas",
      default_bro_detail_session_id: "bro-detail-atlas",
    });

    render(<App />);

    expect(await screen.findByText("Bro detail")).toBeInTheDocument();
    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-1", "atlas"));
  });

  it("starts the shell voice control through the Conversational AI connector path", async () => {
    window.history.replaceState({}, "", "/bros/atlas?sid=session-1");
    render(<RouterProvider router={getRouter()} />);

    await screen.findByText("Bro detail");
    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-1", "atlas"));
    connectorMock.prepareSttSession.mockClear();
    connectorMock.startSttSession.mockClear();
    fireEvent.click(screen.getByTestId("voice-session-start"));

    await waitFor(() => expect(connectorMock.prepareConnectorSession).toHaveBeenCalledWith({
      synapse_session_id: "session-1",
    }));
    expect(connectorMock.activateConnectorSession).toHaveBeenCalledWith({
      prepared_session_id: "prepared-1",
    });
    expect(connectorMock.prepareSttSession).not.toHaveBeenCalled();
    expect(connectorMock.startSttSession).not.toHaveBeenCalled();
  });

  it("keeps ConvoAI toolkit transcript updates display-only", async () => {
    window.history.replaceState({}, "", "/bros/atlas?sid=session-1");
    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("voice-session-start"));
    await waitFor(() => expect(connectorMock.activateConnectorSession).toHaveBeenCalled());

    await act(async () => {
      voiceHarness.voiceEvents.TRANSCRIPT_UPDATED?.([
        {
          uid: "101-voice-room",
          turn_id: 7,
          text: "Please inspect the settings page.",
          status: 1,
          metadata: {
            object: "user.transcription",
            final: true,
            language: "en-US",
            start_ms: 1234,
          },
        },
      ]);
      await Promise.resolve();
    });

    expect(clientMock.submitAgoraVoiceEvent).not.toHaveBeenCalled();

    await act(async () => {
      voiceHarness.voiceEvents.TRANSCRIPT_UPDATED?.([
        {
          uid: "101-voice-room",
          turn_id: 7,
          text: "Please inspect the settings page.",
          status: 1,
          metadata: {
            object: "user.transcription",
            final: true,
          },
        },
        {
          uid: "9001-voice-room",
          turn_id: 8,
          text: "I can help with that.",
          status: 1,
          metadata: {
            object: "assistant.transcription",
            final: true,
          },
        },
        {
          uid: "101-voice-room",
          turn_id: 9,
          text: "Actually",
          status: 0,
          metadata: {
            object: "user.transcription",
            final: false,
          },
        },
      ]);
      await Promise.resolve();
    });

    expect(clientMock.submitAgoraVoiceEvent).not.toHaveBeenCalled();
  });

  it("renders sidebar Bro and Node counts from the shell snapshot", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-1",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-forge",
          status: "idle",
          current_task_id: null,
        },
        {
          persona_id: "persona-atlas",
          name: "Atlas",
          avatar: "atlas",
          base_prompt: "",
          executor_node_id: null,
          status: "offline",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-forge",
          name: "Workshop Mini",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });

    render(<App />);

    const sidebar = await screen.findByTestId("newbro-sidebar");
    await waitFor(() => expect(within(sidebar).getByRole("button", { name: "Bros" })).toHaveTextContent("2"));
    expect(within(sidebar).getByRole("button", { name: "Nodes" })).toHaveTextContent("1");
  });

  it("shows the current account in the sidebar and logs out to the signup screen", async () => {
    clientMock.bootstrapPublicUser.mockResolvedValueOnce({
      user: { user_id: "user-1", email: "owner@example.com" },
      session_id: "session-1",
      default_persona_id: null,
      default_bro_detail_session_id: null,
    });

    render(<App />);

    const sidebar = await screen.findByTestId("newbro-sidebar");
    expect(within(sidebar).getByText("owner@example.com")).toBeInTheDocument();

    fireEvent.click(within(sidebar).getByTestId("sidebar-logout"));

    await waitFor(() => expect(clientMock.logoutPublicUser).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("Sign up")).toBeInTheDocument());
    expect(socketHarness.socket.close).toHaveBeenCalled();
    expect(window.location.search).toBe("");
    expect(screen.queryByTestId("newbro-sidebar")).not.toBeInTheDocument();
  });

  it("blocks an unbound runtime Bro detail behind inline node setup", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: null,
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByTestId("bro-setup-gate")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Set up this Bro before talking" })).toBeInTheDocument();
    expect(screen.queryByTestId("voice-session-start")).not.toBeInTheDocument();
    expect(screen.queryByText("Current draft")).not.toBeInTheDocument();
    expect(clientMock.setVoiceTarget).not.toHaveBeenCalled();
  });

  it("creates a node, binds it to an unbound Bro, then unlocks Bro detail after refresh", async () => {
    const unboundSnapshot = {
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: null,
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    };
    const boundSnapshot = {
      ...unboundSnapshot,
      personas: [
        {
          ...unboundSnapshot.personas[0],
          executor_node_id: "node-1",
        },
      ],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Local node",
          enabled_executors: ["codex"],
          connected_executors: [],
          connection_status: "disconnected",
          token_hint: "tok...0001",
          last_connected_at: null,
          last_seen_at: null,
          acpx_agent: null,
        },
      ],
    };
    clientMock.getSessionSnapshot
      .mockResolvedValueOnce(unboundSnapshot)
      .mockResolvedValueOnce(boundSnapshot);
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    fireEvent.click(await screen.findByTestId("bro-setup-create-node"));

    await waitFor(() => expect(clientMock.createExecutorNode).toHaveBeenCalledWith("session-existing", {
      name: "Rook local node",
      enabled_executors: ["codex"],
    }));
    expect(clientMock.updatePersona).toHaveBeenCalledWith("session-existing", "persona-rook", {
      executor_node_id: "node-1",
    });
    expect(await screen.findByText(/newbro executor run/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("bro-setup-open-detail"));

    expect(await screen.findByText("Current draft")).toBeInTheDocument();
    expect(screen.getByTestId("voice-session-start")).toBeInTheDocument();
    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-existing", "persona-rook"));
  });


  it("opens a Bro detail page when a Home card is clicked", async () => {
    render(<RouterProvider router={getRouter()} />);

    const atlasCard = await screen.findByTestId("bro-card-atlas");
    fireEvent.click(atlasCard);

    expect(await screen.findByText("Bro detail")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Atlas" })).toBeInTheDocument();
    expect(screen.getByText("Current draft")).toBeInTheDocument();
    expect(screen.queryByText("Draft Brain")).not.toBeInTheDocument();
    expect(window.location.pathname).toBe("/bros/atlas");
    expect(window.location.search).toBe("?sid=session-1");
  });

  it("renders a Bro detail route directly with the active shell session", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    const rendered = render(<RouterProvider router={getRouter()} />);

    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-existing"));
    expect(await screen.findByText("Bro detail")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Forge" })).toBeInTheDocument();
    expect(screen.getByText("No draft yet. Hold the mic to start shaping one.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Hold to Talk" })).toBeInTheDocument();
    expect(screen.queryByText("Ready · mic off")).not.toBeInTheDocument();
    await waitFor(() => expect(clientMock.setVoiceTarget).toHaveBeenCalledWith("session-existing", "forge"));

    rendered.unmount();

    await waitFor(() => expect(clientMock.clearVoiceTarget).toHaveBeenCalledWith("session-existing"));
  });

  it("renders the dedicated mobile walkie route with live runtime channels", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-mobile",
          root_task_id: "task-mobile",
          parent_task_id: null,
          title: "Sketch mobile handoff",
          goal: "Sketch mobile handoff details.",
          status: "running",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-mobile",
          task_revision: 0,
          latest_instruction: "Sketch mobile handoff details.",
          metadata: { persona_id: "persona-atlas" },
        },
      ],
      execution_sessions: [],
      execution_runs: [
        {
          run_id: "run-mobile",
          task_id: "task-mobile",
          execution_session_id: "exec-session-mobile",
          executor_type: "codex",
          status: "running",
          claimed_by: "worker-1",
          run_revision: 0,
          latest_progress_message: "Inspecting the mobile UI export.",
          output_summary: null,
          block_reason: null,
          failure_reason: null,
          metadata: {},
        },
      ],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-atlas",
          name: "Atlas",
          avatar: "fox",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-mobile",
        },
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: null,
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByTestId("mobile-walkie")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Walkie" })).toBeInTheDocument();
    expect(screen.getByText("1 live · 0 queued · 1 idle")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-bro-row-persona-atlas")).toHaveTextContent("Sketch mobile handoff");
    expect(window.location.pathname).toBe("/mobile");
    expect(window.location.search).toBe("?sid=session-existing");
  });

  it("selects a mobile bro channel and submits text through the shell socket", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: null,
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/mobile?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const forgeChannel = await screen.findByTestId("mobile-channel-persona-forge");
    fireEvent.click(forgeChannel);

    expect(await screen.findByTestId("mobile-bro-focus-persona-forge")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Please draft the launch note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(clientMock.sendSocketMessage).toHaveBeenCalled());
    expect(clientMock.sendSocketMessage.mock.calls.at(-1)?.[2]).toBe("Please draft the launch note");
  });

  it("publishes the Bro detail mic before muting it", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("button", { name: "Hold to Talk" })).toBeInTheDocument();
    expect(screen.queryByText("Ready · mic off")).not.toBeInTheDocument();
    expect(voiceHarness.rtcClient.publish).toHaveBeenCalledWith([voiceHarness.micTrack]);
    expect(voiceHarness.micTrack.setEnabled).not.toHaveBeenCalledWith(false);
    expect(voiceHarness.micTrack.setMuted).toHaveBeenCalledWith(true);
    expect(
      voiceHarness.rtcClient.publish.mock.invocationCallOrder[0],
    ).toBeLessThan(voiceHarness.micTrack.setMuted.mock.invocationCallOrder[0]);

    const micButton = screen.getByRole("button", { name: "Hold to Talk" });
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 1 });
        await Promise.resolve();
      });
      expect(voiceHarness.micTrack.setMuted).toHaveBeenCalledWith(false);
      expect(screen.queryByText("Ready · mic off")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Release to finish" })).toBeInTheDocument();
      expect(screen.queryByTestId("talking-bars")).not.toBeInTheDocument();
      fireEvent.blur(micButton);
      expect(voiceHarness.micTrack.setMuted).toHaveBeenLastCalledWith(false);
      const callsBeforeRelease = voiceHarness.micTrack.setMuted.mock.calls.length;

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 1 });
        await Promise.resolve();
      });
      expect(screen.queryByText("Ready · mic off")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hold to Talk" })).toBeInTheDocument();
      expect(voiceHarness.micTrack.setMuted).toHaveBeenCalledTimes(callsBeforeRelease);

      await act(async () => {
        vi.advanceTimersByTime(499);
        await Promise.resolve();
      });
      expect(voiceHarness.micTrack.setMuted).toHaveBeenCalledTimes(callsBeforeRelease);

      await act(async () => {
        vi.advanceTimersByTime(1);
        await Promise.resolve();
      });
      expect(voiceHarness.micTrack.setMuted).toHaveBeenLastCalledWith(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps Bro detail RTC debug and unparsed stream messages out of the UI", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];

    await act(async () => {
      transcriptHandler(200101, { nope: true });
    });

    expect(screen.queryByText(/Voice debug:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/unparsed stream-message/)).not.toBeInTheDocument();
  });

  it("does not poll STT status from Bro detail", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });

    expect(connectorMock.querySttSession).not.toHaveBeenCalled();
    expect(screen.queryByText(/Voice debug:/)).not.toBeInTheDocument();
  });

  it("keeps the Bro detail STT session alive across shell stream re-renders", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("button", { name: "Hold to Talk" })).toBeInTheDocument();
    await waitFor(() => expect(connectorMock.startSttSession).toHaveBeenCalledTimes(1));
    expect(connectorMock.prepareSttSession).toHaveBeenCalledTimes(1);
    expect(connectorMock.leaveSttSession).not.toHaveBeenCalled();

    await act(async () => {
      socketHarness.emitMessage({
        type: "user_message_appended",
        sequence: 99,
        message_id: "msg-rerender",
        text: "Trigger a shell render.",
      });
      await Promise.resolve();
    });

    expect(connectorMock.prepareSttSession).toHaveBeenCalledTimes(1);
    expect(connectorMock.startSttSession).toHaveBeenCalledTimes(1);
    expect(connectorMock.leaveSttSession).not.toHaveBeenCalled();
  });

  it("clears stale Bro detail STT resources when heartbeat reports an unknown session", async () => {
    vi.useFakeTimers();
    try {
      connectorMock.heartbeatSttSession.mockRejectedValueOnce(new Error("Unknown STT session."));
      window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

      render(<RouterProvider router={getRouter()} />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(connectorMock.startSttSession).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.advanceTimersByTime(15_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(connectorMock.heartbeatSttSession).toHaveBeenCalledWith("stt-1");
      expect(voiceHarness.micTrack.stop).toHaveBeenCalled();
      expect(voiceHarness.micTrack.close).toHaveBeenCalled();
      expect(voiceHarness.rtcClient.leave).toHaveBeenCalled();
      expect(connectorMock.leaveSttSession).not.toHaveBeenCalled();
      expect(screen.getByText("STT session expired. Start voice again to create a fresh session.")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders final Bro detail transcript and returned draft content", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 11 });
        await Promise.resolve();
        transcriptHandler(200101, {
          text: "Build a calm\nlanding page",
          isFinal: false,
          time: 100,
          textTs: 110,
        });
        transcriptHandler(200101, {
          text: "with soft motion",
          isFinal: false,
          time: 200,
          textTs: 210,
        });
        transcriptHandler(200101, {
          text: "with",
          isFinal: true,
          time: 200,
          textTs: 220,
        });
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
      });

      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 11 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("Build a calm landing page with soft motion")).toBeInTheDocument();
    expect(screen.queryByText("Listening live")).not.toBeInTheDocument();
    expect(screen.queryByText("Completed turns appear here when ASR marks a segment final.")).not.toBeInTheDocument();
    expect(await screen.findByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();
    expect(screen.getByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();
    expect(submittedSttPartialEvents().map(([, event]: any[]) => event.text)).toEqual([
      "Build a calm landing page",
      "Build a calm landing page with soft motion",
    ]);
    expectLastSttFinal("Build a calm landing page with soft motion");
  });

  it("renders live Bro detail draft cleaner stream previews", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    await screen.findByRole("button", { name: "Hold to Talk" });
    await waitFor(() => expect(clientMock.openSessionStream).toHaveBeenCalledWith(
      "session-existing",
      expect.any(Object),
    ));

    await act(async () => {
      socketHarness.emitMessage({
        type: "draft_output_started",
        sequence: 31,
        request_id: "live-draft-3",
      });
      await Promise.resolve();
    });
    await act(async () => {
      socketHarness.emitMessage({
        type: "draft_output_delta",
        sequence: 32,
        request_id: "live-draft-3",
        delta: "Preview ",
      });
      await Promise.resolve();
    });
    await act(async () => {
      socketHarness.emitMessage({
        type: "draft_output_delta",
        sequence: 33,
        request_id: "live-draft-3",
        delta: "draft",
      });
      await Promise.resolve();
    });

    expect(screen.getByText("Preview draft")).toBeInTheDocument();

    await act(async () => {
      socketHarness.emitMessage({
        type: "draft_output_completed",
        sequence: 34,
        request_id: "live-draft-3",
        draft_session_id: "draft-live-1",
        draft_text: "Preview draft complete.",
      });
      await Promise.resolve();
    });

    expect(screen.getByText("Preview draft complete.")).toBeInTheDocument();
  });

  it("sends the current Bro detail draft to execution and resets the draft workspace", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-forge",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-forge",
          name: "Workshop Mini",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/persona-forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, {
        text: "Build a calm landing page",
        isFinal: false,
        time: 100,
        textTs: 110,
      });
      await Promise.resolve();
    });
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 21 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 21 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();
    const sendButton = screen.getByRole("button", { name: "Send to Bro" });
    expect(sendButton).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(sendButton);
      await Promise.resolve();
    });

    await waitFor(() => expect(clientMock.sendDraft).toHaveBeenCalledWith("session-existing", {
      draft_session_id: "draft-session-1",
      draft_revision_id: "draft-rev-1",
    }));
    expect(screen.queryByText("Design a polished landing page with a calm hero section.")).not.toBeInTheDocument();
    expect(screen.getByText("No draft yet. Hold the mic to start shaping one.")).toBeInTheDocument();
    expect(screen.getByText("Latest transcript will appear here.")).toBeInTheDocument();
  });

  it("keeps the Bro detail draft visible when sending fails", async () => {
    clientMock.sendDraft.mockImplementationOnce(async () => {
      throw new Error("send failed");
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-forge",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, {
        text: "Build a calm landing page",
        isFinal: false,
        time: 100,
        textTs: 110,
      });
      await Promise.resolve();
    });
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 22 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 22 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send to Bro" }));
      await Promise.resolve();
    });

    await waitFor(() => expect(clientMock.sendDraft).toHaveBeenCalledWith("session-existing", {
      draft_session_id: "draft-session-1",
      draft_revision_id: "draft-rev-1",
    }));
    expect(await screen.findAllByText("send failed")).not.toHaveLength(0);
    expect(screen.getByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();
    expect(screen.queryByText("No draft yet. Hold the mic to start shaping one.")).not.toBeInTheDocument();
  });

  it("clears the current Bro detail draft without sending it", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-forge",
          name: "Forge",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-forge",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, {
        text: "Build a calm landing page",
        isFinal: false,
        time: 100,
        textTs: 110,
      });
      await Promise.resolve();
    });
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 23 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 23 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("Design a polished landing page with a calm hero section.")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Clear Draft" }));
      await Promise.resolve();
    });

    await waitFor(() => expect(clientMock.clearDraft).toHaveBeenCalledWith("session-existing", {
      draft_session_id: "draft-session-1",
    }));
    expect(clientMock.sendDraft).not.toHaveBeenCalled();
    expect(screen.queryByText("Design a polished landing page with a calm hero section.")).not.toBeInTheDocument();
    expect(screen.getByText("No draft yet. Hold the mic to start shaping one.")).toBeInTheDocument();
  });

  it("prints Bro detail transcript debug as segments displayText and words", async () => {
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, {
        text: "hello world",
        isFinal: false,
        uid: 101,
        time: 100,
        textTs: 120,
        words: [
          { text: "hello", startMs: 100, durationMs: 50, isFinal: true, confidence: 0.95 },
          { text: "world", startMs: 150, durationMs: 60, isFinal: false, confidence: 0.9 },
        ],
      });
    });

    const candidateLog = debugSpy.mock.calls.find(
      ([label]) => label === "[BroDetail][STT] received candidate",
    );
    expect(candidateLog?.[1]).toMatchObject({
      displayText: "hello world",
      segments: [
        {
          key: "101:100",
          uid: "101",
          startTime: 100,
          text: "hello world",
          textTs: 120,
          arrivalIndex: 1,
        },
      ],
      words: [
        { text: "hello", startMs: 100, durationMs: 50, isFinal: true, confidence: 0.95 },
        { text: "world", startMs: 150, durationMs: 60, isFinal: false, confidence: 0.9 },
      ],
      protobuf: null,
    });
    expect(candidateLog?.[1]).not.toHaveProperty("candidate");
    expect(candidateLog?.[1]).not.toHaveProperty("raw");
    debugSpy.mockRestore();
  });

  it("keeps only the latest textTs for each timed Chinese Bro detail sentence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 15 });
        await Promise.resolve();
        transcriptHandler(200101, { text: "好像在一场大", isFinal: false, time: 100, textTs: 110 });
        transcriptHandler(200101, { text: "型音乐演唱会上面", isFinal: false, time: 100, textTs: 120 });
        transcriptHandler(200101, { text: "南", isFinal: false, time: 200, textTs: 210 });
        transcriptHandler(200101, { text: "美人在美国超级", isFinal: false, time: 200, textTs: 220 });
        transcriptHandler(200101, { text: "碗上面", isFinal: false, time: 200, textTs: 230 });
        transcriptHandler(200101, { text: "大 型", isFinal: false, time: 300, textTs: 310 });
        transcriptHandler(200101, { text: "音乐", isFinal: false, time: 300, textTs: 320 });
        transcriptHandler(200101, { text: "音", isFinal: true, time: 300, textTs: 330 });
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 15 });
        await Promise.resolve();
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    expect(await screen.findByText("型音乐演唱会上面碗上面音乐")).toBeInTheDocument();
    expect(screen.queryByText(/好像在一场大/)).not.toBeInTheDocument();
    expect(screen.queryByText(/美人在美国超级/)).not.toBeInTheDocument();
    expectLastSttFinal("型音乐演唱会上面碗上面音乐");
  });

  it("submits untimed Bro detail transcript candidates as live partials without accepting them for final commit", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, {
        result: {
          text: "Still listening to this sentence",
          isFinal: false,
        },
      });
    });

    expect(screen.queryByText("Still listening to this sentence")).not.toBeInTheDocument();
    expect(screen.queryByText("Listening live")).not.toBeInTheDocument();
    expect(screen.queryByText("Completed turns appear here when ASR marks a segment final.")).not.toBeInTheDocument();
    expect(submittedSttPartialEvents()).toHaveLength(1);
    expect(submittedSttPartialEvents()[0]?.[1]).toEqual(expect.objectContaining({
      type: "stt.partial",
      text: "Still listening to this sentence",
      timestamp_ms: 1,
      metadata: expect.objectContaining({
        reason: "drop-missing-time-metadata",
      }),
    }));
    expect(submittedSttFinalEvents()).toHaveLength(0);
  });

  it("renders official provisional transcript wrappers and commits after release plus silence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 12 });
        await Promise.resolve();
        transcriptHandler(200101, {
          transcript: {
            uid: 101,
            language: "zh-CN",
            text: "先展示临时转写",
            isFinal: true,
            offset: 0,
            duration: 760,
            textTs: 1_751_438_273_939,
          },
        });
        await Promise.resolve();
      });

      expect(screen.getByText("先展示临时转写")).toBeInTheDocument();
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 12 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
      expectLastSttFinal("先展示临时转写");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps only the latest textTs inside one Bro detail sentence and submits once after mic release plus silence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, { text: "第二个片段", isFinal: false, time: 100, textTs: 120 });
      transcriptHandler(200101, { text: "第一个片段", isFinal: false, time: 100, textTs: 110 });
    });

    expect(screen.getByText("第二个片段")).toBeInTheDocument();
    expect(screen.queryByText("第一个片段第二个片段")).not.toBeInTheDocument();
    expect(submittedSttFinalEvents()).toHaveLength(0);

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 1 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 1 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() => expect(submittedSttFinalEvents()).toHaveLength(1));
    expectLastSttFinal("第二个片段");
  });

  it("drops stale Bro detail ASR candidates for the same sentence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, { uid: 101, text: "OK，第一个问题", isFinal: false, time: 100, textTs: 300, seqnum: 2 });
      transcriptHandler(200101, { uid: 101, text: "OK", isFinal: false, time: 100, textTs: 200, seqnum: 3 });
      transcriptHandler(200101, { uid: 101, text: "OK，旧修订", isFinal: false, time: 100, textTs: 300, seqnum: 1 });
    });

    expect(screen.getByText("OK，第一个问题")).toBeInTheDocument();
    expect(screen.queryByText("OK")).not.toBeInTheDocument();
    expect(submittedSttFinalEvents()).toHaveLength(0);
  });

  it("holds final fragments until the next non-final for the same sentence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 13 });
        await Promise.resolve();
        transcriptHandler(200101, { uid: 101, text: "ABCDEFG", isFinal: false, time: 100, textTs: 300 });
      });
      expect(screen.getByText("ABCDEFG")).toBeInTheDocument();

      await act(async () => {
        transcriptHandler(200101, { uid: 101, text: "ABC", isFinal: true, time: 100, textTs: 310 });
        await Promise.resolve();
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
      });
      expect(screen.getByText("ABCDEFG")).toBeInTheDocument();
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 13 });
        await Promise.resolve();
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
      expectLastSttFinal("ABCDEFG");

      await act(async () => {
        transcriptHandler(200101, { uid: 101, text: "DEFG", isFinal: false, time: 100, textTs: 320 });
      });

      expect(screen.getByText("ABCDEFG")).toBeInTheDocument();
      expect(screen.queryByText("ABCDEFGDEFG")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rebuilds Bro detail ASR by sentence start time using latest textTs per sentence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    await act(async () => {
      transcriptHandler(200101, { uid: 101, text: "第二句", isFinal: false, time: 200, textTs: 210 });
      transcriptHandler(200101, { uid: 101, text: "第一句后半", isFinal: false, time: 100, textTs: 120 });
      transcriptHandler(200101, { uid: 101, text: "第一句前半", isFinal: false, time: 100, textTs: 110 });
    });

    const expectedTranscript = "第一句后半第二句";
    expect(await screen.findByText(expectedTranscript)).toBeInTheDocument();

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 3 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 3 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() => expect(submittedSttFinalEvents()).toHaveLength(1));
    expectLastSttFinal(expectedTranscript);
  });

  it("submits Bro detail ASR once after release plus silence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 2 });
        await Promise.resolve();
        transcriptHandler(200101, { text: "好像在一场大 型音乐", isFinal: false, time: 100, textTs: 110 });
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
      });

      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        fireEvent.pointerUp(micButton, { pointerId: 2 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(1);
      expectLastSttFinal("好像在一场大 型音乐");
    } finally {
      vi.useRealTimers();
    }
  });

  it("submits final-only Bro detail ASR after release plus silence", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 24 });
        await Promise.resolve();
        fireEvent.pointerUp(micButton, { pointerId: 24 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(400);
        transcriptHandler(200101, { uid: 101, text: "Final only draft", isFinal: true, time: 100, textTs: 110 });
        await Promise.resolve();
      });
      expect(screen.getByText("Final only draft")).toBeInTheDocument();
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_200);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(1);
      expectLastSttFinal("Final only draft");
    } finally {
      vi.useRealTimers();
    }
  });

  it("includes tail transcript and resets the Bro detail draft update timer after release", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 14 });
        await Promise.resolve();
        transcriptHandler(200101, { uid: 101, text: "Build the draft", isFinal: false, time: 100, textTs: 110 });
        fireEvent.pointerUp(micButton, { pointerId: 14 });
        await Promise.resolve();
      });

      await act(async () => {
        vi.advanceTimersByTime(400);
        transcriptHandler(200101, { uid: 101, text: "with delayed transcript", isFinal: false, time: 200, textTs: 210 });
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1_199);
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(0);

      await act(async () => {
        vi.advanceTimersByTime(1);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(submittedSttFinalEvents()).toHaveLength(1);
      expectLastSttFinal("Build the draft with delayed transcript");
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels the Bro detail post-release mute and draft debounce when pressed again during the tail", async () => {
    window.history.replaceState({}, "", "/bros/forge?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const micButton = await screen.findByRole("button", { name: "Hold to Talk" });
    const transcriptHandler = voiceHarness.rtcClient.on.mock.calls.find(
      ([eventName]) => eventName === "stream-message",
    )?.[1];
    expect(transcriptHandler).toBeTypeOf("function");

    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.pointerDown(micButton, { pointerId: 15 });
        await Promise.resolve();
        transcriptHandler(200101, { uid: 101, text: "Keep recording", isFinal: false, time: 100, textTs: 110 });
        fireEvent.pointerUp(micButton, { pointerId: 15 });
        await Promise.resolve();
      });

      const trueCallsAfterFirstRelease = voiceHarness.micTrack.setMuted.mock.calls.filter(
        (call: any[]) => call[0] === true,
      ).length;

      await act(async () => {
        vi.advanceTimersByTime(300);
        fireEvent.pointerDown(micButton, { pointerId: 16 });
        await Promise.resolve();
      });

      await act(async () => {
        vi.advanceTimersByTime(1_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(voiceHarness.micTrack.setMuted.mock.calls.filter((call: any[]) => call[0] === true)).toHaveLength(
        trueCallsAfterFirstRelease,
      );
      expect(voiceHarness.micTrack.setMuted).toHaveBeenLastCalledWith(false);
      expect(submittedSttFinalEvents()).toHaveLength(0);
      expect(screen.getByRole("button", { name: "Release to finish" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("loads durable history without rendering interaction memory on Home", async () => {
    clientMock.getConversationSnapshot.mockResolvedValueOnce({
      session_id: "session-1",
      conversation_history: [
        { role: "assistant", text: "Hello from Newbro.", message_id: "msg-1" },
        { role: "user", text: "Please summarize the plan.", message_id: "msg-2" },
      ],
    } as any);

    render(<App />);

    expect(await screen.findByTestId("bros-panel")).toBeInTheDocument();
    expect(clientMock.getConversationSnapshot).toHaveBeenCalledWith("session-1");
    expect(screen.queryByText("Hello from Newbro.")).not.toBeInTheDocument();
    expect(screen.queryByText("Please summarize the plan.")).not.toBeInTheDocument();
    expect(screen.queryByText("Transcript will appear here.")).not.toBeInTheDocument();
    expect(screen.queryByText("2 turns")).not.toBeInTheDocument();
  });

  it("resumes the shell session from the sid query parameter", async () => {
    window.history.replaceState({}, "", "/?sid=session-existing");

    render(<App />);

    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-existing"));
    expect(clientMock.bootstrapPublicUser).not.toHaveBeenCalled();
    expect(await screen.findByTestId("bros-panel")).toBeInTheDocument();
    expect(screen.queryByText("Session session-existing")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?sid=session-existing");
  });

  it("shows resume fallback in a floating global message that auto-dismisses", async () => {
    vi.useFakeTimers();
    clientMock.bootstrapPublicUser.mockResolvedValueOnce({
      user: { user_id: "user-1" },
      session_id: "session-2",
      default_persona_id: null,
      default_bro_detail_session_id: null,
    });
    clientMock.getSessionSnapshot.mockImplementation(async (sessionId: string) => {
      if (sessionId === "session-missing") {
        throw new Error("Request failed with status 404");
      }
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
    });
    window.history.replaceState({}, "", "/?sid=session-missing");

    render(<App />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("global-message")).toBeInTheDocument();
    expect(screen.getByTestId("global-message")).toHaveClass("fixed");
    expect(screen.getByText(/Could not resume the requested session/)).toBeInTheDocument();
    expect(screen.getByText(/session-missing/)).toBeInTheDocument();
    expect(screen.getByTestId("bros-panel")).toBeInTheDocument();
    expect(screen.queryByText("Session session-2")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(5_999);
    });
    expect(screen.getByTestId("global-message")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByTestId("global-message")).not.toBeInTheDocument();
    expect(clientMock.bootstrapPublicUser).toHaveBeenCalledTimes(1);
    expect(clientMock.getSessionSnapshot).toHaveBeenNthCalledWith(1, "session-missing");
    expect(clientMock.getSessionSnapshot).toHaveBeenNthCalledWith(2, "session-2");
    expect(window.location.search).toBe("?sid=session-2");
    vi.useRealTimers();
  });

  it("keeps Newbro stream events out of the simplified Home surface", async () => {
    render(<App />);

    await screen.findByTestId("bros-panel");
    expect(screen.queryByTestId("voice-session-start")).not.toBeInTheDocument();
    expect(screen.queryByText("Transcript will appear here.")).not.toBeInTheDocument();

    await act(async () => {
      socketHarness.emitMessage({
        type: "user_message_appended",
        message_id: "msg-user-1",
        role: "user",
        text: "Please create a follow-up task.",
        source: "user",
      });
    });

    expect(screen.queryByText("Please create a follow-up task.")).not.toBeInTheDocument();
    expect(screen.queryByText("Me")).not.toBeInTheDocument();

    await act(async () => {
      socketHarness.emitMessage({
        type: "assistant_response_completed",
        request_id: "req-1",
        message_id: "msg-assistant-1",
        reply_text: "Hello. How can I help you today?",
        conversational_act: "model_reply",
        affected_task_ids: [],
      });
    });

    expect(screen.queryByText("Hello. How can I help you today?")).not.toBeInTheDocument();
    expect(screen.queryByText("NewBro")).not.toBeInTheDocument();
    expect(screen.queryByText("Transcript will appear here.")).not.toBeInTheDocument();
    expect(screen.queryByText("2 turns")).not.toBeInTheDocument();
    expect(screen.queryByText("Session session-1")).not.toBeInTheDocument();
  });

  it("switches to runtime persona cards when persona data exists", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-1",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-1",
          name: "Rook",
          avatar: "/avatars/avatar-01.png",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-1234",
        },
        {
          persona_id: "persona-2",
          name: "Vale",
          avatar: "/avatars/avatar-02.png",
          base_prompt: "",
          executor_node_id: "node-2",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
        {
          node_id: "node-2",
          name: "Travel Laptop",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...2222",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("Rook")).toBeInTheDocument();
    expect(screen.getByText("Vale")).toBeInTheDocument();
    expect(screen.queryByText("2 live")).not.toBeInTheDocument();
    expect(screen.queryByText("Atlas")).not.toBeInTheDocument();
  });


  it("does not apply legacy press effects to Home Bro cards", async () => {
    render(<RouterProvider router={getRouter()} />);

    const forgeCard = await screen.findByTestId("bro-card-forge");
    fireEvent.pointerDown(forgeCard);
    fireEvent.pointerUp(forgeCard);

    const card = within(screen.getByTestId("bro-card-forge"));
    expect(screen.getByTestId("bro-card-forge")).not.toHaveAttribute("aria-pressed");
    expect(card.queryByText("preview")).not.toBeInTheDocument();
    expect(card.queryByText("mic on")).not.toBeInTheDocument();
    expect(card.queryByTestId("talking-bars")).not.toBeInTheDocument();
    expect(card.getByText("busy")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });

  it("loads the Bros page directly from the URL", async () => {
    window.history.replaceState({}, "", "/bros?sid=session-1");
    const router = getRouter();

    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Worker Bros")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/bros");
    expect(window.location.search).toBe("?sid=session-1");
    expect(clientMock.bootstrapPublicUser).not.toHaveBeenCalled();
    expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-1");
  });

  it("loads the Nodes page directly from the URL", async () => {
    window.history.replaceState({}, "", "/nodes");
    const router = getRouter();

    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Executor Nodes")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/nodes");
  });

  it("shows a shell-level API error instead of blank data when bootstrap fails", async () => {
    clientMock.bootstrapPublicUser.mockRejectedValueOnce(new Error("Request failed with status 404"));

    const router = getRouter();
    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Unable to reach the Newbro API")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This deployment must proxy /api/* requests to the backend before the shell can load live data.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Atlas")).not.toBeInTheDocument();
  });

  it("shows signup instead of a shell API error when a requested session requires auth", async () => {
    window.history.replaceState({}, "", "/?sid=session-private");
    clientMock.getSessionSnapshot.mockRejectedValueOnce(new Error("Authentication required."));
    clientMock.bootstrapPublicUser.mockRejectedValueOnce(new Error("Authentication required."));

    const router = getRouter();
    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Sign up")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Email")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Invitation code")).toBeInTheDocument();
    expect(screen.queryByText("Unable to reach the Newbro API")).not.toBeInTheDocument();
  });

  it("signs up with email and fixed invitation code before bootstrapping", async () => {
    clientMock.bootstrapPublicUser.mockRejectedValueOnce(new Error("Authentication required."));

    render(<App />);

    expect(await screen.findByText("Sign up")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Email"), { target: { value: "User@Example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Invitation code"), { target: { value: "open-sesame" } });
    fireEvent.click(screen.getByRole("button", { name: "Enter" }));

    await waitFor(() => expect(clientMock.signupPublicUser).toHaveBeenCalledWith("User@Example.com", "open-sesame"));
    await waitFor(() => expect(clientMock.getSessionSnapshot).toHaveBeenCalledWith("session-1"));
    expect(await screen.findByTestId("bros-panel")).toBeInTheDocument();
  });

  it("keeps shell snapshot bros visible when the Bros page refresh fails", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-1",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-1",
          name: "Rook",
          avatar: "fox",
          base_prompt: "Stay direct.",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-1",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    clientMock.listPersonas.mockRejectedValueOnce(new Error("Bros refresh failed."));
    clientMock.listExecutorNodes.mockRejectedValueOnce(new Error("Nodes refresh failed."));

    window.history.replaceState({}, "", "/bros");
    const router = getRouter();
    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Worker Bros")).toBeInTheDocument();
    expect(screen.getByText("Rook")).toBeInTheDocument();
    expect(
      screen.getByText("Bros refresh failed. Showing the latest shell snapshot instead."),
    ).toBeInTheDocument();
  });

  it("keeps shell snapshot nodes visible when the Nodes page refresh fails", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-1",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-1",
          name: "Rook",
          avatar: "fox",
          base_prompt: "Stay direct.",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-1",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    clientMock.listExecutorNodes.mockRejectedValueOnce(new Error("Node refresh failed."));
    clientMock.listPersonas.mockRejectedValueOnce(new Error("Persona refresh failed."));

    window.history.replaceState({}, "", "/nodes");
    const router = getRouter();
    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByText("Executor Nodes")).toBeInTheDocument();
    expect(screen.getByText("Studio Mac")).toBeInTheDocument();
    expect(
      screen.getByText("Node refresh failed. Showing the latest shell snapshot instead."),
    ).toBeInTheDocument();
  });

  it("renders Bro detail task panel without repeated title or fallback summary", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-1234",
          root_task_id: "task-1234",
          parent_task_id: null,
          title: "Prepare draft execution",
          goal: "Prepare the execution plan.",
          status: "queued",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-1234",
          task_revision: 0,
          latest_instruction: "Prepare the execution plan.",
          metadata: {},
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-1234",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("button", { name: "Stop Task" })).toBeInTheDocument();
    expect(screen.queryByText("Runner Brain")).not.toBeInTheDocument();
    expect(screen.getAllByText("Prepare draft execution")).toHaveLength(1);
    const statusIcon = screen.getByTestId("bro-detail-bot-status-icon");
    expect(statusIcon).toHaveClass("nb-bot-orb-active");
    expect(statusIcon.querySelector(".nb-live-dot")).toBeInTheDocument();
    expect(screen.queryByText("queued: Prepare draft execution")).not.toBeInTheDocument();
    expect(screen.queryByText("Latest summary")).not.toBeInTheDocument();
  });

  it("renders markdown safely in Bro detail task text", async () => {
    const progressMarkdown = "Progress has **bold detail** and `inline_code`.\n\n- queued step\n- shipped step";
    const latestSummary = "Latest _summary_ with [docs](https://example.com/docs) and <span data-testid=\"raw-html\">raw html</span>.";
    const recentSummary = "Recent summary:\n\n1. One\n2. Two\n\n```ts\nconst value = 1;\n```\n\n| A | B |\n| - | - |\n| C | D |";

    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-active",
          root_task_id: "task-active",
          parent_task_id: null,
          title: "Render markdown task",
          goal: "Render markdown task details.",
          status: "running",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-active",
          task_revision: 0,
          latest_instruction: "Render markdown task details.",
          metadata: { persona_id: "persona-rook" },
        },
        {
          task_id: "task-recent",
          root_task_id: "task-recent",
          parent_task_id: null,
          title: "Previous markdown task",
          goal: "Preserve previous markdown details.",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-recent",
          task_revision: 0,
          latest_instruction: "Preserve previous markdown details.",
          metadata: { persona_id: "persona-rook" },
        },
      ],
      execution_sessions: [],
      execution_runs: [
        {
          run_id: "run-active",
          task_id: "task-active",
          execution_session_id: "exec-session-1",
          executor_type: "codex",
          status: "running",
          claimed_by: "worker-1",
          run_revision: 0,
          latest_progress_message: progressMarkdown,
          output_summary: null,
          block_reason: null,
          failure_reason: null,
          metadata: {},
        },
      ],
      execution_modes: [],
      bindings: [],
      summaries: [
        {
          task_id: "task-active",
          operational_summary: "Operational markdown summary",
          conversational_summary: latestSummary,
          latest_user_visible_status: "running",
          needs_user_input: false,
        },
        {
          task_id: "task-recent",
          operational_summary: "Operational recent markdown summary",
          conversational_summary: recentSummary,
          latest_user_visible_status: "completed",
          needs_user_input: false,
        },
      ],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-active",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Studio Mac",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    const { container } = render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("button", { name: "Stop Task" })).toBeInTheDocument();
    expect(container.querySelector(".nb-status-card")).toHaveStyle("--nb-task-progress: 60%");
    expect(screen.queryByText("Runner Brain")).not.toBeInTheDocument();
    expect(screen.getByText("bold detail").tagName).toBe("STRONG");
    expect(screen.getAllByText("summary").some((element) => element.tagName === "EM")).toBe(true);
    expect(screen.getByText("inline_code").tagName).toBe("CODE");
    expect(screen.getByText("queued step").closest("ul")).toBeInTheDocument();
    const recentTaskCard = screen.getByText("Previous markdown task").closest("article");
    expect(recentTaskCard).toBeInTheDocument();
    expect(within(recentTaskCard!).getByText(/Recent summary:/)).toHaveClass("nb-task-desc");
    expect(recentTaskCard!.querySelector("ol")).not.toBeInTheDocument();
    expect(recentTaskCard!.querySelector("table")).not.toBeInTheDocument();
    expect(recentTaskCard!.querySelector("code")).not.toBeInTheDocument();
    const link = screen.getAllByRole("link", { name: "docs" })[0];
    expect(link).toHaveAttribute("href", "https://example.com/docs");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(container.querySelector("[data-testid='raw-html']")).not.toBeInTheDocument();
    expect(screen.getAllByText(/<span data-testid="raw-html">raw html<\/span>/).length).toBeGreaterThan(0);
  });

  it("renders Bro detail idle task panel without nested idle progress card", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "qz",
          enabled_executors: ["codex"],
          connected_executors: ["codex"],
          connection_status: "connected",
          token_hint: "tok...1111",
          last_connected_at: null,
          last_seen_at: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    const { container } = render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByRole("button", { name: "Stop Task" })).toBeInTheDocument();
    expect(container.querySelector(".nb-status-card")).toHaveStyle("--nb-task-progress: 0%");
    expect(screen.queryByText("Runner Brain")).not.toBeInTheDocument();
    expect(screen.getAllByText("Waiting for assignment")).toHaveLength(1);
    expect(screen.queryByText("Current state")).not.toBeInTheDocument();
    expect(screen.queryByText("qz is connected. This bro can pick up the next task immediately.")).not.toBeInTheDocument();
    expect(screen.queryByText("Available for routing through qz.")).not.toBeInTheDocument();
    expect(screen.getByText("Ready to pick up the next runtime assignment.")).toBeInTheDocument();
    const statusIcon = screen.getByTestId("bro-detail-bot-status-icon");
    expect(statusIcon).not.toHaveClass("nb-bot-orb-active");
    expect(statusIcon.querySelector(".nb-live-dot")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop Task" })).toBeDisabled();
  });

  it("shows a copyable local node command when a Bro task is waiting for an executor", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-waiting",
          root_task_id: "task-waiting",
          parent_task_id: null,
          title: "Run generated draft",
          goal: "Run the generated draft.",
          status: "waiting_executor",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-waiting",
          task_revision: 0,
          latest_instruction: "Run the generated draft.",
          metadata: { persona_id: "persona-rook" },
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-waiting",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [
        {
          node_id: "node-1",
          name: "Local node",
          enabled_executors: ["codex"],
          connected_executors: [],
          connection_status: "disconnected",
          token_hint: "tok...0001",
          last_connected_at: null,
          last_seen_at: null,
          acpx_agent: null,
        },
      ],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const copyButton = await screen.findByRole("button", { name: "Copy local node command" });
    fireEvent.click(copyButton);

    await waitFor(() => expect(clientMock.revealExecutorNodeConnectCommand).toHaveBeenCalledWith("session-existing", "node-1"));
    expect(clientMock.createExecutorNode).not.toHaveBeenCalled();
    expect(clientMock.updatePersona).not.toHaveBeenCalled();
    expect(await screen.findByText(/newbro executor run/)).toBeInTheDocument();
  });

  it("submits a cancel command from the Bro detail Stop Task button", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-active",
          root_task_id: "task-active",
          parent_task_id: null,
          title: "Run active scrape",
          goal: "Run the active scrape.",
          status: "running",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-active",
          task_revision: 0,
          latest_instruction: "Run the active scrape.",
          metadata: { persona_id: "persona-rook" },
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-active",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const stopButton = await screen.findByRole("button", { name: "Stop Task" });
    expect(stopButton).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(stopButton);
      await Promise.resolve();
    });

    await waitFor(() => expect(clientMock.submitTaskCommand).toHaveBeenCalledWith("session-existing", {
      command_type: "cancel_task",
      task_id: "task-active",
      reason: "Stopped from Bro detail Runner Brain.",
    }));
  });

  it("keeps the current task visible when Stop Task fails", async () => {
    clientMock.submitTaskCommand.mockImplementationOnce(async () => {
      throw new Error("stop failed");
    });
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-active",
          root_task_id: "task-active",
          parent_task_id: null,
          title: "Run active scrape",
          goal: "Run the active scrape.",
          status: "running",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-active",
          task_revision: 0,
          latest_instruction: "Run the active scrape.",
          metadata: { persona_id: "persona-rook" },
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-active",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    const stopButton = await screen.findByRole("button", { name: "Stop Task" });
    await act(async () => {
      fireEvent.click(stopButton);
      await Promise.resolve();
    });

    expect(await screen.findByText("Run active scrape")).toBeInTheDocument();
    expect((await screen.findAllByText("stop failed")).length).toBeGreaterThan(0);
  });

  it("keeps completed Bro tasks visible in Bro detail recent tasks after persona is released", async () => {
    const completedSummary = "Published notes with the final itinerary.\nIncluded transfer timing, backup route notes, fare caveats, and follow-up reminders so the whole task context stays visible in the detail page.";
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-done",
          root_task_id: "task-done",
          parent_task_id: null,
          title: "Publish travel notes",
          goal: "Publish the final travel notes.",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-done",
          task_revision: 0,
          latest_instruction: "Publish the final travel notes.",
          metadata: { persona_id: "persona-rook", bro_detail_session_id: "bro-detail-current" },
        },
      ],
      execution_sessions: [],
      execution_runs: [
        {
          run_id: "run-done",
          task_id: "task-done",
          execution_session_id: "exec-session-1",
          executor_type: "codex",
          status: "completed",
          claimed_by: "worker-1",
          run_revision: 0,
          latest_progress_message: null,
          output_summary: completedSummary,
          block_reason: null,
          failure_reason: null,
          metadata: {},
        },
      ],
      execution_modes: [],
      bindings: [],
      summaries: [
        {
          task_id: "task-done",
          operational_summary: "Completed: Publish travel notes",
          conversational_summary: completedSummary,
          latest_user_visible_status: "completed",
          needs_user_input: false,
        },
      ],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          bro_detail_session_id: "bro-detail-current",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Recent tasks")).toBeInTheDocument();
    expect(screen.getByText("Publish travel notes")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    const taskCard = screen.getByText("Publish travel notes").closest("article");
    expect(taskCard).toBeInTheDocument();
    const description = within(taskCard!).getByText(/Published notes with the final itinerary/);
    expect(description).toHaveClass("nb-task-desc");
    expect(description).not.toHaveTextContent("\n");
  });

  it("does not duplicate the active task in Bro detail recent tasks", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-old",
          root_task_id: "task-old",
          parent_task_id: null,
          title: "Archive old result",
          goal: "Archive the old result.",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-old",
          task_revision: 0,
          latest_instruction: "Archive the old result.",
          metadata: { persona_id: "persona-rook" },
        },
        {
          task_id: "task-active",
          root_task_id: "task-active",
          parent_task_id: null,
          title: "Run active scrape",
          goal: "Run the active scrape.",
          status: "running",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "workspace-task-active",
          task_revision: 0,
          latest_instruction: "Run the active scrape.",
          metadata: { persona_id: "persona-rook" },
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-1",
          status: "busy",
          current_task_id: "task-active",
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Recent tasks")).toBeInTheDocument();
    expect(screen.getByText("Run active scrape")).toBeInTheDocument();
    expect(screen.getByText("Archive old result")).toBeInTheDocument();
    expect(screen.getAllByText("Run active scrape")).toHaveLength(1);
  });

  it("hides previous Bro detail generations from recent tasks after rebinding", async () => {
    clientMock.getSessionSnapshot.mockResolvedValueOnce({
      session_id: "session-existing",
      tasks: [
        {
          task_id: "task-old-generation",
          root_task_id: "task-old-generation",
          parent_task_id: null,
          title: "Old node result",
          goal: "Summarize the old node result.",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "ws-bro-detail-old",
          task_revision: 0,
          latest_instruction: "Summarize the old node result.",
          metadata: { persona_id: "persona-rook", bro_detail_session_id: "bro-detail-old" },
        },
        {
          task_id: "task-current-generation",
          root_task_id: "task-current-generation",
          parent_task_id: null,
          title: "Current node result",
          goal: "Summarize the current node result.",
          status: "completed",
          priority: 5,
          interruptible: true,
          requires_confirmation: false,
          preferred_executor: "codex",
          session_affinity: "ws-bro-detail-current",
          task_revision: 0,
          latest_instruction: "Summarize the current node result.",
          metadata: { persona_id: "persona-rook", bro_detail_session_id: "bro-detail-current" },
        },
      ],
      execution_sessions: [],
      execution_runs: [],
      execution_modes: [],
      bindings: [],
      summaries: [],
      notification_candidates: [],
      personas: [
        {
          persona_id: "persona-rook",
          name: "Rook",
          avatar: "bro",
          base_prompt: "",
          executor_node_id: "node-2",
          bro_detail_session_id: "bro-detail-current",
          status: "idle",
          current_task_id: null,
        },
      ],
      interaction_requests: [],
      attention_items: [],
      executor_capabilities: [],
      executor_nodes: [],
    });
    window.history.replaceState({}, "", "/bros/persona-rook?sid=session-existing");

    render(<RouterProvider router={getRouter()} />);

    expect(await screen.findByText("Recent tasks")).toBeInTheDocument();
    expect(screen.getByText("Current node result")).toBeInTheDocument();
    expect(screen.queryByText("Old node result")).not.toBeInTheDocument();
  });

  it("navigates between left-menu pages and preserves browser history", async () => {
    window.history.replaceState({}, "", "/?sid=session-1");
    const router = getRouter();
    render(<RouterProvider router={router} />);
    await act(async () => {
      await router.load();
    });

    expect(await screen.findByTestId("bros-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bros" }));
    await waitFor(() => expect(window.location.pathname).toBe("/bros"));
    expect(window.location.search).toBe("?sid=session-1");
    expect(await screen.findByText("Worker Bros")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Nodes" }));
    await waitFor(() => expect(window.location.pathname).toBe("/nodes"));
    expect(window.location.search).toBe("?sid=session-1");
    expect(await screen.findByText("Executor Nodes")).toBeInTheDocument();

    await act(async () => {
      window.history.back();
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() => expect(window.location.pathname).toBe("/bros"));
    expect(window.location.search).toBe("?sid=session-1");
    expect(await screen.findByText("Worker Bros")).toBeInTheDocument();
  });
});

describe("buildBroCardModels", () => {
  it("falls back to the seeded sample bros when no personas are available", () => {
    const bros = buildBroCardModels([]);

    expect(bros.map((bro) => bro.name)).toEqual(["Atlas", "Scout", "Muse", "Forge"]);
    expect(bros.every((bro) => bro.source === "sample")).toBe(true);
  });

  it("maps runtime personas into bro cards with busy and idle states", () => {
    const bros = buildBroCardModels([
      {
        persona_id: "persona-1",
        name: "Rook",
        avatar: "/avatars/avatar-01.png",
        executor_node_id: "node-1",
        bro_detail_session_id: "bro-detail-1",
        status: "busy",
        current_task_id: "task-1234",
      },
      {
        persona_id: "persona-2",
        name: "Vale",
        avatar: "/avatars/avatar-02.png",
        executor_node_id: null,
        bro_detail_session_id: "bro-detail-2",
        status: "idle",
        current_task_id: null,
      },
    ], [
      {
        node_id: "node-1",
        name: "Studio Mac",
        connection_status: "connected",
      },
    ]);

    expect(bros).toHaveLength(2);
    expect(bros[0]).toMatchObject({
      id: "persona-1",
      name: "Rook",
      status: "busy",
      liveState: "live",
      taskTitle: "Handle active runtime work",
      source: "runtime",
    });
    expect(bros[1]).toMatchObject({
      id: "persona-2",
      name: "Vale",
      status: "idle",
      liveState: "unbound",
      progressLabel: "Idle",
      source: "runtime",
    });
  });

  it("maps queued runtime task state into bro progress", () => {
    const bros = buildBroCardModels([
      {
        persona_id: "persona-1",
        name: "Rook",
        avatar: "/avatars/avatar-01.png",
        executor_node_id: "node-1",
        bro_detail_session_id: "bro-detail-1",
        status: "busy",
        current_task_id: "task-1234",
      },
    ], [
      {
        node_id: "node-1",
        name: "Studio Mac",
        connection_status: "connected",
      },
    ], [], [], [
      {
        task_id: "task-1234",
        root_task_id: "task-1234",
        parent_task_id: null,
        title: "Prepare draft execution",
        goal: "Prepare the execution plan.",
        status: "queued",
        priority: 5,
        interruptible: true,
        requires_confirmation: false,
        preferred_executor: "codex",
        session_affinity: "workspace-task-1234",
        task_revision: 0,
        latest_instruction: "Prepare the execution plan.",
        metadata: {},
      },
    ]);

    expect(bros[0]).toMatchObject({
      id: "persona-1",
      status: "busy",
      taskTitle: "Prepare draft execution",
      progressLabel: "queued",
      progress: 18,
    });
    expect(bros[0].progressDetails).toEqual([]);
    expect(bros[0].progressDetails).not.toContain("Prepare the execution plan.");
    expect(bros[0].progressDetails).not.toContain("queued: Prepare draft execution");
  });

  it("uses non-redundant runtime summaries as bro progress detail", () => {
    const bros = buildBroCardModels([
      {
        persona_id: "persona-1",
        name: "Rook",
        avatar: "/avatars/avatar-01.png",
        executor_node_id: "node-1",
        bro_detail_session_id: "bro-detail-1",
        status: "busy",
        current_task_id: "task-1234",
      },
    ], [
      {
        node_id: "node-1",
        name: "Studio Mac",
        connection_status: "connected",
      },
    ], [], [
      {
        task_id: "task-1234",
        operational_summary: "Checked available morning flights and narrowed the hotel area.",
        conversational_summary: "Checked available morning flights and narrowed the hotel area.",
        latest_user_visible_status: "running",
        needs_user_input: false,
      },
    ], [
      {
        task_id: "task-1234",
        root_task_id: "task-1234",
        parent_task_id: null,
        title: "Book Beijing travel",
        goal: "Book flights and hotel for Beijing.",
        status: "running",
        priority: 5,
        interruptible: true,
        requires_confirmation: false,
        preferred_executor: "codex",
        session_affinity: "workspace-task-1234",
        task_revision: 0,
        latest_instruction: "Book flights and hotel for Beijing.",
        metadata: {},
      },
    ]);

    expect(bros[0].progressDetails).toEqual(["Checked available morning flights and narrowed the hotel area."]);
  });

  it("filters runtime summary fallbacks out of bro progress detail", () => {
    const bros = buildBroCardModels([
      {
        persona_id: "persona-1",
        name: "Rook",
        avatar: "/avatars/avatar-01.png",
        executor_node_id: "node-1",
        bro_detail_session_id: "bro-detail-1",
        status: "busy",
        current_task_id: "task-1234",
      },
    ], [
      {
        node_id: "node-1",
        name: "Studio Mac",
        connection_status: "connected",
      },
    ], [], [
      {
        task_id: "task-1234",
        operational_summary: "Running: Book Beijing travel",
        conversational_summary: "Running: Book Beijing travel",
        latest_user_visible_status: "running",
        needs_user_input: false,
      },
    ], [
      {
        task_id: "task-1234",
        root_task_id: "task-1234",
        parent_task_id: null,
        title: "Book Beijing travel",
        goal: "Book flights and hotel for Beijing.",
        status: "running",
        priority: 5,
        interruptible: true,
        requires_confirmation: false,
        preferred_executor: "codex",
        session_affinity: "workspace-task-1234",
        task_revision: 0,
        latest_instruction: "Book flights and hotel for Beijing.",
        metadata: {},
      },
    ]);

    expect(bros[0].progressDetails).toEqual([]);
  });
});
