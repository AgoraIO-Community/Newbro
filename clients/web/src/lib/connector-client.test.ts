import { afterEach, describe, expect, it, vi } from "vitest";

function okJsonResponse(payload: object): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

describe("connector-client transport base URL handling", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("uses relative connector paths by default", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        ready: true,
        service_base_url: "http://127.0.0.1:8010",
        defaults: {},
        missing_requirements: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.getConnectorConfig();

    expect(fetchMock).toHaveBeenCalledWith("/api/connectors/agora-convoai/config");
  });

  it("uses the configured connector base URL for fetches", async () => {
    vi.stubEnv("VITE_CONNECTOR_BASE_URL", "https://connectors.example.com");
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        ready: true,
        service_base_url: "https://connectors.example.com",
        defaults: {},
        missing_requirements: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.getConnectorConfig();
    await client.stopConnectorSession("binding-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "https://connectors.example.com/api/connectors/agora-convoai/config",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "https://connectors.example.com/api/connectors/agora-convoai/sessions/stop",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ binding_id: "binding-1" }),
      },
    );
  });

  it("normalizes trailing slashes on the configured connector base URL", async () => {
    vi.stubEnv("VITE_CONNECTOR_BASE_URL", "https://connectors.example.com/runtime/");
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
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
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.prepareConnectorSession();

    expect(fetchMock).toHaveBeenCalledWith(
      "https://connectors.example.com/runtime/api/connectors/agora-convoai/sessions/prepare",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
  });

  it("passes synapse_session_id through connector prepare requests", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        prepared_session_id: "prepared-1",
        app_id: "agora-app",
        channel_name: "session-1",
        token: "voice-token",
        uid: 101,
        user_rtm_uid: "101-session-1",
        agent: { uid: "9001" },
        agent_rtm_uid: "9001-session-1",
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
          agent_rtm_uid: "9001-session-1",
          rtc_uid: 101,
          rtm_user_id: "101-session-1",
          enable_string_uid: false,
          enable_rtm: true,
          data_channel: "rtm",
          enable_metrics: true,
          enable_error_message: true,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.prepareConnectorSession({ synapse_session_id: "session-1" });

    expect(fetchMock).toHaveBeenCalledWith("/api/connectors/agora-convoai/sessions/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ synapse_session_id: "session-1" }),
    });
  });

  it("uses sendBeacon for best-effort stop signaling on page teardown", async () => {
    vi.stubEnv("VITE_CONNECTOR_BASE_URL", "https://connectors.example.com/runtime/");
    const sendBeaconMock = vi.fn(() => true);
    Object.defineProperty(globalThis.navigator, "sendBeacon", {
      configurable: true,
      value: sendBeaconMock,
    });

    const client = await import("./connector-client");

    const result = client.stopConnectorSessionBeacon("binding-1");

    expect(result).toBe(true);
    expect(sendBeaconMock).toHaveBeenCalledTimes(1);
    const firstCall = sendBeaconMock.mock.calls[0] as unknown as [string, unknown];
    expect(firstCall[0]).toBe(
      "https://connectors.example.com/runtime/api/connectors/agora-convoai/sessions/stop",
    );
  });
  it("prepares STT browser join credentials through the connector route", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        prepared_stt_session_id: "prepared-stt-1",
        app_id: "agora-app",
        channel_name: "nbstt-session-bro-random",
        token: "rtc-token",
        uid: 101,
        status: "prepared",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    const response = await client.prepareSttSession({
      synapse_session_id: "session-1",
      assigned_bro_id: "bro-1",
    });

    expect(response.uid).toBe(101);
    expect(response.channel_name).toBe("nbstt-session-bro-random");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/connectors/agora-convoai/stt/sessions/prepare",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ synapse_session_id: "session-1", assigned_bro_id: "bro-1" }),
      },
    );
  });

  it("starts STT sessions through the connector route", async () => {
    const fetchMock = vi.fn(async () =>
      okJsonResponse({
        stt_session_id: "stt-1",
        app_id: "agora-app",
        channel_name: "session-1",
        token: "rtc-token",
        uid: 101,
        pub_bot_uid: 100101,
        sub_bot_uid: 100102,
        agent_id: "agent-1",
        status: "started",
        languages: ["zh-CN", "en-US"],
        subscribe_audio_uids: ["101"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    const response = await client.startSttSession({
      prepared_stt_session_id: "prepared-stt-1",
    });

    expect(response.stt_session_id).toBe("stt-1");
    expect(response.languages).toEqual(["zh-CN", "en-US"]);
    expect(response.subscribe_audio_uids).toEqual(["101"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/connectors/agora-convoai/stt/sessions/start",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prepared_stt_session_id: "prepared-stt-1" }),
      },
    );
  });

  it("heartbeats STT sessions through the connector route", async () => {
    const fetchMock = vi.fn(async () => okJsonResponse({ status: "active" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    const response = await client.heartbeatSttSession("stt-1");

    expect(response.status).toBe("active");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/connectors/agora-convoai/stt/sessions/heartbeat",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stt_session_id: "stt-1" }),
      },
    );
  });

  it("leaves STT sessions through the connector route", async () => {
    const fetchMock = vi.fn(async () => okJsonResponse({ status: "stopped" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.leaveSttSession({ stt_session_id: "stt-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/connectors/agora-convoai/stt/sessions/leave",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stt_session_id: "stt-1" }),
      },
    );
  });

  it("stops STT sessions through the connector route", async () => {
    const fetchMock = vi.fn(async () => okJsonResponse({ status: "stopped" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = await import("./connector-client");

    await client.stopSttSession("stt-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/connectors/agora-convoai/stt/sessions/stop",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stt_session_id: "stt-1" }),
      },
    );
  });

});

describe("connector-client HTTP error formatting", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("formats nested JSON detail strings from failed connector responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(
        JSON.stringify({ detail: JSON.stringify({ detail: "core: db failed, task not found", reason: "TaskNotFound" }) }),
        { status: 404 },
      )),
    );
    const client = await import("./connector-client");

    await expect(client.prepareSttSession({ synapse_session_id: "session-1", assigned_bro_id: "bro-1" })).rejects.toThrow(
      "core: db failed, task not found",
    );
  });
});
