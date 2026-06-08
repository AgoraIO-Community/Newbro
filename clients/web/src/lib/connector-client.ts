import { ensureOk } from "./http-errors";
export interface ConnectorConfig {
  ready: boolean;
  service_base_url: string;
  defaults: {
    profile?: string;
    channel_name?: string | null;
    display_name?: string;
    agent_instructions?: string;
    agent_greeting?: string;
    agent_uid?: number;
    user_uid?: number;
  };
  missing_requirements: string[];
}

export interface ConnectorSessionPrepareRequest {
  synapse_session_id?: string;
  profile?: string;
  channel_name?: string;
  display_name?: string;
  agent_instructions?: string;
  agent_greeting?: string;
  agent_uid?: number;
  user_uid?: number;
}

export interface ConnectorSessionActivateRequest {
  prepared_session_id: string;
}

export interface ConnectorSessionDiagnostics {
  convoai_area: string;
  selected_url: string;
  runtime_session_id: string | null;
  asr_vendor: string;
  asr_credential_mode: string;
  asr_model: string;
  tts_vendor: string;
  tts_credential_mode: string;
  tts_model: string;
  agent_uid: string;
  agent_rtm_uid: string;
  rtc_uid: string | number | null;
  rtm_user_id: string;
  enable_string_uid: boolean;
  enable_rtm: boolean;
  data_channel: string | null;
  enable_metrics: boolean;
  enable_error_message: boolean;
}

export interface ConnectorPrepareResponse {
  prepared_session_id: string;
  app_id: string;
  channel_name: string;
  token: string;
  uid: number;
  user_rtm_uid: string;
  agent: {
    uid: string;
  };
  agent_rtm_uid: string;
  enable_string_uid: boolean;
  profile: string | null;
  display_name: string | null;
  diagnostics: ConnectorSessionDiagnostics;
}

export interface ConnectorActivateResponse {
  prepared_session_id: string;
  binding_id: string;
  synapse_session_id: string;
  runtime_session_id: string;
  chat_completions_url: string;
  app_id: string;
  channel_name: string;
  token: string;
  uid: number;
  user_rtm_uid: string;
  agent: {
    uid: string;
  };
  agent_rtm_uid: string;
  enable_string_uid: boolean;
  profile: string | null;
  display_name: string | null;
  diagnostics: ConnectorSessionDiagnostics;
}

const API_PREFIX = "/api";
const configuredConnectorBaseUrl = getConfiguredConnectorBaseUrl();

function getConfiguredConnectorBaseUrl(): URL | null {
  const raw = import.meta.env.VITE_CONNECTOR_BASE_URL?.trim();
  if (!raw) {
    return null;
  }
  return new URL(raw, window.location.origin);
}

function withTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function normalizePath(path: string): string {
  return path.replace(/^\/+/, "");
}

function buildConnectorHttpUrl(path: string): string {
  if (configuredConnectorBaseUrl === null) {
    return path;
  }
  return new URL(normalizePath(path), withTrailingSlash(configuredConnectorBaseUrl.href)).toString();
}

export async function getConnectorConfig(): Promise<ConnectorConfig> {
  const response = await fetch(buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/config`));
  return (await ensureOk(response)).json();
}

export async function prepareConnectorSession(
  payload: ConnectorSessionPrepareRequest = {},
): Promise<ConnectorPrepareResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/sessions/prepare`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function activateConnectorSession(
  payload: ConnectorSessionActivateRequest,
): Promise<ConnectorActivateResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/sessions/activate`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function stopConnectorSession(bindingId: string): Promise<void> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/sessions/stop`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ binding_id: bindingId }),
    },
  );
  await ensureOk(response);
}

export function stopConnectorSessionBeacon(bindingId: string): boolean {
  if (typeof navigator === "undefined" || typeof navigator.sendBeacon !== "function") {
    return false;
  }
  const payload = JSON.stringify({ binding_id: bindingId });
  return navigator.sendBeacon(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/sessions/stop`),
    new Blob([payload], { type: "application/json" }),
  );
}

export interface SttSessionStartRequest {
  prepared_stt_session_id: string;
  languages?: string[];
}

export interface SttSessionPrepareRequest {
  synapse_session_id: string;
  assigned_bro_id: string;
  user_uid?: number;
}

export interface SttSessionPrepareResponse {
  prepared_stt_session_id: string;
  app_id: string;
  channel_name: string;
  token: string;
  uid: number;
  status: string;
}

export interface SttSessionStartResponse {
  stt_session_id: string;
  app_id: string;
  channel_name: string;
  token: string;
  uid: number;
  pub_bot_uid: number;
  sub_bot_uid: number;
  agent_id: string;
  status: string;
  languages: string[];
  subscribe_audio_uids: string[];
}

export interface SttSessionQueryResponse {
  stt_session_id: string;
  agent_id: string;
  status: string;
  raw: Record<string, unknown>;
}

export interface SttSessionHeartbeatResponse {
  status: string;
}

export async function prepareSttSession(payload: SttSessionPrepareRequest): Promise<SttSessionPrepareResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/prepare`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function startSttSession(payload: SttSessionStartRequest): Promise<SttSessionStartResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/start`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function querySttSession(sttSessionId: string): Promise<SttSessionQueryResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/${sttSessionId}`),
  );
  return (await ensureOk(response)).json();
}

export async function heartbeatSttSession(sttSessionId: string): Promise<SttSessionHeartbeatResponse> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/heartbeat`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stt_session_id: sttSessionId }),
    },
  );
  return (await ensureOk(response)).json();
}

export async function leaveSttSession(payload: { stt_session_id?: string; prepared_stt_session_id?: string }): Promise<void> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/leave`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  await ensureOk(response);
}

export async function stopSttSession(sttSessionId: string): Promise<void> {
  const response = await fetch(
    buildConnectorHttpUrl(`${API_PREFIX}/connectors/agora-convoai/stt/sessions/stop`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stt_session_id: sttSessionId }),
    },
  );
  await ensureOk(response);
}
