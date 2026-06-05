import { ensureOk } from "./http-errors";
import type {
  ConversationSnapshot,
  BroThreadPageResponse,
  BroTimelineTurnPageResponse,
  DiagnosticTimelineResponse,
  ExecutorNodeCredentialIssue,
  ExecutorNodeRecord,
  SessionResponse,
  SessionSnapshot,
  SessionStreamEvent,
  TaskCommandType,
} from "../types";

export const API_PREFIX = "/api";
const NEWBRO_CLI_INSTALL_URL =
  "https://raw.githubusercontent.com/AgoraIO-Community/Newbro/main/scripts/install-newbro-cli.sh";
const configuredApiBaseUrl = getConfiguredApiBaseUrl();

function getConfiguredApiBaseUrl(): URL | null {
  const raw = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!raw) {
    return null;
  }
  return new URL(raw, window.location.origin);
}

export function getEffectiveApiBaseUrl(): string {
  if (configuredApiBaseUrl === null) {
    const { protocol, hostname, port } = window.location;
    if (
      (hostname === "localhost" || hostname === "127.0.0.1") &&
      port !== "" &&
      port !== "8000"
    ) {
      return `${protocol}//${hostname}:8000`;
    }
    return window.location.origin;
  }
  return configuredApiBaseUrl.href.replace(/\/$/, "");
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\"'\"'`)}'`;
}

export interface ExecutorRunCommandOptions {
  enabledExecutors?: string[];
  acpxAgent?: string | null;
  audioLanguage?: string | null;
  whisperModel?: string | null;
}

export interface ExecutorConnectCommands {
  installOnly: string;
  installConnect: string;
  runOnly: string;
  connectSettings: string;
}

function buildExecutorRunArgs(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): string[] {
  const args = [
    "executor",
    "run",
    "--base-url",
    shellQuote(getEffectiveApiBaseUrl()),
    "--node-id",
    shellQuote(nodeId),
    "--token",
    shellQuote(token),
  ];
  for (const executorType of options?.enabledExecutors ?? []) {
    args.push("--enabled-executor", shellQuote(executorType));
  }
  if (options?.acpxAgent) {
    args.push("--acpx-agent", shellQuote(options.acpxAgent));
  }
  if (options?.audioLanguage) {
    args.push("--audio-language", shellQuote(options.audioLanguage));
  }
  if (options?.whisperModel) {
    args.push("--whisper-model", shellQuote(options.whisperModel));
  }
  return args;
}

export function buildExecutorRunCommand(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): string {
  return ["newbro", ...buildExecutorRunArgs(nodeId, token, options)].join(" ");
}

export function buildExecutorConnectSettingsURL(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): string {
  const params = new URLSearchParams();
  params.set("base_url", getEffectiveApiBaseUrl());
  params.set("node_id", nodeId);
  params.set("token", token);
  for (const executorType of options?.enabledExecutors ?? []) {
    params.append("enabled_executor", executorType);
  }
  return `newbro://connect?${params.toString()}`;
}

export function buildExecutorInstallOnlyCommand(): string {
  return ["curl", "-fsSL", NEWBRO_CLI_INSTALL_URL, "|", "sh"].join(" ");
}

export function buildExecutorInstallConnectCommand(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): string {
  return [
    "curl",
    "-fsSL",
    NEWBRO_CLI_INSTALL_URL,
    "|",
    "sh",
    "-s",
    "--",
    ...buildExecutorRunArgs(nodeId, token, options),
  ].join(" ");
}

export function buildExecutorConnectCommands(
  nodeId: string,
  token: string,
  options?: ExecutorRunCommandOptions,
): ExecutorConnectCommands {
  return {
    installOnly: buildExecutorInstallOnlyCommand(),
    installConnect: buildExecutorInstallConnectCommand(nodeId, token, options),
    runOnly: buildExecutorRunCommand(nodeId, token, options),
    connectSettings: buildExecutorConnectSettingsURL(nodeId, token, options),
  };
}

function withTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function normalizePath(path: string): string {
  return path.replace(/^\/+/, "");
}

export function buildHttpUrl(path: string): string {
  if (configuredApiBaseUrl === null) {
    return path;
  }
  return new URL(normalizePath(path), withTrailingSlash(configuredApiBaseUrl.href)).toString();
}

function buildWebSocketUrl(path: string): string {
  if (configuredApiBaseUrl === null) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${path}`;
  }

  const socketUrl = new URL(normalizePath(path), withTrailingSlash(configuredApiBaseUrl.href));
  if (socketUrl.protocol === "https:") {
    socketUrl.protocol = "wss:";
  } else if (socketUrl.protocol === "http:") {
    socketUrl.protocol = "ws:";
  }
  return socketUrl.toString();
}

export async function createSession(): Promise<SessionResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions`), {
    method: "POST",
  });
  return (await ensureOk(response)).json();
}

export interface PublicUser {
  user_id: string;
  email: string | null;
}

export interface AuthMeResponse {
  user: PublicUser;
}

export interface PublicBootstrapResponse {
  user: PublicUser;
  session_id: string;
  default_persona_id: string | null;
  default_bro_detail_session_id: string | null;
}

export async function redeemInvite(code: string): Promise<AuthMeResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/auth/invites/redeem`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  return (await ensureOk(response)).json();
}

export async function signupPublicUser(email: string, code: string): Promise<AuthMeResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/auth/signup`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  });
  return (await ensureOk(response)).json();
}

export async function getCurrentUser(): Promise<AuthMeResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/auth/me`));
  return (await ensureOk(response)).json();
}

export async function logoutPublicUser(): Promise<void> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/auth/logout`), {
    method: "POST",
  });
  await ensureOk(response);
}

export async function claimDevice(userCode: string): Promise<void> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/devices/pair/claim`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_code: userCode.trim().toUpperCase() }),
  });
  await ensureOk(response);
}

export async function bootstrapPublicUser(): Promise<PublicBootstrapResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/me/bootstrap`));
  return (await ensureOk(response)).json();
}

export async function getSessionSnapshot(sessionId: string): Promise<SessionSnapshot> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}`));
  return (await ensureOk(response)).json();
}

export async function listBroThreadsPage(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    limit?: number;
    cursor?: string | null;
  },
): Promise<BroThreadPageResponse> {
  const params = new URLSearchParams();
  params.set("target_persona_id", payload.targetPersonaId);
  params.set("limit", String(payload.limit ?? 25));
  if (payload.cursor) params.set("cursor", payload.cursor);
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads?${params.toString()}`));
  return (await ensureOk(response)).json();
}

export async function listBroTimelinePage(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    threadId: string;
    limit?: number;
    cursor?: string | null;
  },
): Promise<BroTimelineTurnPageResponse> {
  const params = new URLSearchParams();
  params.set("target_persona_id", payload.targetPersonaId);
  params.set("limit", String(payload.limit ?? 15));
  if (payload.cursor) params.set("cursor", payload.cursor);
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/timeline?${params.toString()}`),
  );
  return (await ensureOk(response)).json();
}

export async function openBroThread(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    threadId: string;
  },
): Promise<SessionSnapshot> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/open`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: payload.targetPersonaId }),
  });
  return (await ensureOk(response)).json();
}

export async function closeBroThread(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    threadId: string;
  },
): Promise<SessionSnapshot> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(payload.threadId)}/open`), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_persona_id: payload.targetPersonaId }),
  });
  return (await ensureOk(response)).json();
}

export interface MessageResponse {
  message_id: string;
  reply_text: string;
  conversational_act: string;
  affected_task_ids: string[];
}

export async function sendSessionMessage(sessionId: string, text: string): Promise<MessageResponse> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/messages`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return (await ensureOk(response)).json();
}

export interface AgoraVoiceEventRequest {
  event_id: string;
  session_id: string;
  type: "stt.partial" | "stt.final" | "user.speech_started" | "user.speech_ended" | "assistant.speech_started" | "assistant.speech_ended" | "interaction.interrupted" | "session.started" | "session.ended";
  text?: string;
  language?: string | null;
  timestamp_ms?: number | null;
  target_persona_id?: string | null;
  metadata?: Record<string, unknown>;
}

export async function submitAgoraVoiceEvent(
  sessionId: string,
  event: AgoraVoiceEventRequest,
): Promise<void> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/agora-events`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  });
  await ensureOk(response);
}

export interface ExecutorAudioInstructionResponse {
  audio_instruction_id: string;
  target_persona_id: string;
  target_thread_id: string | null;
  status: string;
  duration_ms: number;
  size_bytes: number;
  transcript_text?: string | null;
}

export async function submitExecutorAudioInstruction(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    targetThreadId?: string | null;
    pcm16: Blob;
    durationMs: number;
    sampleRate: number;
    numChannels: number;
    samplesPerChannel: number;
    createNewThread?: boolean;
    workspaceId?: string | null;
    clientRequestId?: string | null;
  },
): Promise<ExecutorAudioInstructionResponse> {
  const query = new URLSearchParams({
    target_persona_id: payload.targetPersonaId,
    duration_ms: String(payload.durationMs),
    sample_rate: String(payload.sampleRate),
    num_channels: String(payload.numChannels),
    samples_per_channel: String(payload.samplesPerChannel),
  });
  if (payload.targetThreadId) {
    query.set("target_thread_id", payload.targetThreadId);
  }
  if (payload.createNewThread) {
    query.set("create_new_thread", "true");
  }
  if (payload.workspaceId) {
    query.set("workspace_id", payload.workspaceId);
  }
  if (payload.clientRequestId) {
    query.set("client_request_id", payload.clientRequestId);
  }
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-audio-instructions?${query.toString()}`),
    {
      method: "POST",
      headers: { "Content-Type": "audio/pcm" },
      body: payload.pcm16,
    },
  );
  return (await ensureOk(response)).json();
}

export async function submitExecutorTextInstruction(
  sessionId: string,
  payload: {
    targetPersonaId: string;
    targetThreadId?: string | null;
    createNewThread?: boolean;
    workspaceId?: string | null;
    clientRequestId?: string | null;
    planMode?: boolean;
    text: string;
  },
): Promise<{ instruction_id: string; target_persona_id: string; target_thread_id: string | null; status: string }> {
  const body: Record<string, unknown> = {
    target_persona_id: payload.targetPersonaId,
    target_thread_id: payload.targetThreadId ?? null,
    create_new_thread: payload.createNewThread ?? false,
    workspace_id: payload.workspaceId ?? null,
    plan_mode: payload.planMode ?? false,
    text: payload.text,
  };
  if (payload.clientRequestId) {
    body.client_request_id = payload.clientRequestId;
  }
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-text-instructions`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await ensureOk(response)).json();
}

export async function getConversationSnapshot(sessionId: string): Promise<ConversationSnapshot> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/conversation`));
  return (await ensureOk(response)).json();
}

export async function getDiagnosticTimeline(
  sessionId: string,
  params: {
    afterSequence?: number;
    taskId?: string;
    runId?: string;
    executionSessionId?: string;
    requestId?: string;
    eventPrefix?: string;
    minLevel?: string;
    limit?: number;
  } = {},
): Promise<DiagnosticTimelineResponse> {
  const query = new URLSearchParams();
  if (params.afterSequence !== undefined) {
    query.set("after_sequence", String(params.afterSequence));
  }
  if (params.taskId) {
    query.set("task_id", params.taskId);
  }
  if (params.runId) {
    query.set("run_id", params.runId);
  }
  if (params.executionSessionId) {
    query.set("execution_session_id", params.executionSessionId);
  }
  if (params.requestId) {
    query.set("request_id", params.requestId);
  }
  if (params.eventPrefix) {
    query.set("event_prefix", params.eventPrefix);
  }
  if (params.minLevel) {
    query.set("min_level", params.minLevel);
  }
  if (params.limit !== undefined) {
    query.set("limit", String(params.limit));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/diagnostics/timeline${suffix}`),
  );
  return (await ensureOk(response)).json();
}

function openSocket<TEvent>(
  path: string,
  handlers: {
    onOpen: () => void;
    onMessage: (event: TEvent) => void;
    onClose: () => void;
    onError: () => void;
  },
): WebSocket {
  const socket = new WebSocket(buildWebSocketUrl(path));

  socket.addEventListener("open", handlers.onOpen);
  socket.addEventListener("close", handlers.onClose);
  socket.addEventListener("error", handlers.onError);
  socket.addEventListener("message", (messageEvent) => {
    const parsed = JSON.parse(messageEvent.data) as TEvent;
    handlers.onMessage(parsed);
  });

  return socket;
}

export function openSessionStream(
  sessionId: string,
  handlers: {
    onOpen: () => void;
    onMessage: (event: SessionStreamEvent) => void;
    onClose: () => void;
    onError: () => void;
  },
): WebSocket {
  return openSocket<SessionStreamEvent>(`${API_PREFIX}/sessions/${sessionId}/stream`, handlers);
}

export function sendSocketMessage(socket: WebSocket, requestId: string, text: string, targetPersonaId?: string | null) {
  socket.send(
    JSON.stringify({
      type: "send_message",
      request_id: requestId,
      text,
      ...(targetPersonaId ? { target_persona_id: targetPersonaId } : {}),
    }),
  );
}

export function sendSocketCommand(
  socket: WebSocket,
  requestId: string,
  commandType: TaskCommandType,
  targetTaskId: string,
) {
  socket.send(
    JSON.stringify({
      type: "send_command",
      request_id: requestId,
      command_type: commandType,
      task_id: targetTaskId,
    }),
  );
}

export function sendSocketInteractionResolution(
  socket: WebSocket,
  requestId: string,
  interactionRequestId: string,
  action: "approve" | "deny" | "answer" | "confirm" | "cancel",
  options: {
    answerText?: string;
    optionId?: string;
    answers?: Record<string, string[]>;
    reason?: string;
    clientRequestId?: string;
    userVisibleText?: string;
  } = {},
) {
  socket.send(
    JSON.stringify({
      type: "resolve_interaction_request",
      request_id: requestId,
      interaction_request_id: interactionRequestId,
      action,
      answer_text: options.answerText,
      option_id: options.optionId,
      answers: options.answers,
      reason: options.reason,
      client_request_id: options.clientRequestId,
      user_visible_text: options.userVisibleText,
    }),
  );
}

export function sendSocketDraftAsrTurn(
  socket: WebSocket,
  requestId: string,
  payload: {
    raw_text: string;
    normalized_text?: string;
    confidence?: number;
    assigned_bro_id?: string;
  },
) {
  socket.send(
    JSON.stringify({
      type: "submit_asr_turn",
      request_id: requestId,
      raw_text: payload.raw_text,
      normalized_text: payload.normalized_text,
      confidence: payload.confidence,
      assigned_bro_id: payload.assigned_bro_id,
    }),
  );
}

export async function resolveInteractionRequest(
  sessionId: string,
  interactionRequestId: string,
  payload: {
    action: "approve" | "deny" | "answer" | "confirm" | "cancel";
    answer_text?: string;
    option_id?: string;
    answers?: Record<string, string[]>;
    reason?: string;
    client_request_id?: string;
    user_visible_text?: string;
  },
) {
  const response = await fetch(
    buildHttpUrl(
      `${API_PREFIX}/sessions/${sessionId}/interaction-requests/${interactionRequestId}/resolve`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}


// --- Persona API ---

export interface PersonaCreatePayload {
  name: string;
  avatar?: string;
  base_prompt?: string;
  executor_node_id?: string | null;
}

export interface PersonaUpdatePayload {
  name?: string;
  avatar?: string;
  base_prompt?: string;
  executor_node_id?: string | null;
}

export async function listPersonas(sessionId: string) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/personas`));
  return (await ensureOk(response)).json();
}

export async function createPersona(sessionId: string, payload: PersonaCreatePayload) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/personas`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}

export async function updatePersona(
  sessionId: string,
  personaId: string,
  payload: PersonaUpdatePayload,
) {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/personas/${personaId}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function deletePersona(sessionId: string, personaId: string) {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/personas/${personaId}`),
    {
      method: "DELETE",
    },
  );
  return (await ensureOk(response)).json();
}


// --- Executor Nodes API ---

export interface ExecutorNodeCreatePayload {
  name: string;
  enabled_executors: string[];
  acpx_agent?: string | null;
}

export interface ExecutorNodeUpdatePayload {
  name?: string;
  enabled_executors?: string[];
  acpx_agent?: string | null;
}

export async function listExecutorNodes(sessionId: string): Promise<ExecutorNodeRecord[]> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes`));
  return (await ensureOk(response)).json();
}

export async function createExecutorNode(
  sessionId: string,
  payload: ExecutorNodeCreatePayload,
): Promise<ExecutorNodeCredentialIssue> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}

export async function updateExecutorNode(
  sessionId: string,
  nodeId: string,
  payload: ExecutorNodeUpdatePayload,
): Promise<ExecutorNodeRecord> {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes/${nodeId}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  return (await ensureOk(response)).json();
}

export async function rotateExecutorNodeCredentials(
  sessionId: string,
  nodeId: string,
): Promise<ExecutorNodeCredentialIssue> {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes/${nodeId}/credentials/rotate`),
    {
      method: "POST",
    },
  );
  return (await ensureOk(response)).json();
}

export async function revealExecutorNodeConnectCommand(
  sessionId: string,
  nodeId: string,
): Promise<ExecutorNodeCredentialIssue> {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes/${nodeId}/connect-command`),
    {
      method: "POST",
    },
  );
  return (await ensureOk(response)).json();
}

export async function deleteExecutorNode(sessionId: string, nodeId: string) {
  const response = await fetch(
    buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/executor-nodes/${nodeId}`),
    {
      method: "DELETE",
    },
  );
  return (await ensureOk(response)).json();
}


// --- Voice Target API ---

export async function setVoiceTarget(sessionId: string, targetPersonaId: string): Promise<void> {
  await ensureOk(
    await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/voice-target`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_persona_id: targetPersonaId }),
    }),
  );
}

export async function clearVoiceTarget(sessionId: string): Promise<void> {
  await ensureOk(
    await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/voice-target`), {
      method: "DELETE",
    }),
  );
}

export async function submitDraftAsrTurn(
  sessionId: string,
  payload: {
    raw_text: string;
    normalized_text?: string;
    confidence?: number;
    assigned_bro_id?: string;
  },
) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/draft/asr-turns`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}

export async function sendDraft(
  sessionId: string,
  payload: {
    draft_session_id?: string;
    draft_revision_id?: string;
  } = {},
) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/draft/send`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}

export async function submitTaskCommand(
  sessionId: string,
  payload: {
    command_type: TaskCommandType;
    task_id?: string | null;
    reason?: string | null;
    payload?: Record<string, unknown>;
  },
) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/commands`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}

export async function clearDraft(
  sessionId: string,
  payload: {
    draft_session_id?: string;
  } = {},
) {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/sessions/${sessionId}/draft/clear`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await ensureOk(response)).json();
}
