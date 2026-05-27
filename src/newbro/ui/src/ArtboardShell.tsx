import { useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent } from "react";
import { ArrowUp, Check, ChevronLeft, Copy, FileText, Layers, LogOut, MessageSquare, Mic, Plus, Radio, SendHorizontal, Settings, WifiOff, X } from "lucide-react";
import {
  buildExecutorRunCommand,
  clearDraft,
  clearVoiceTarget,
  createExecutorNode,
  createPersona,
  getSessionSnapshot,
  revealExecutorNodeConnectCommand,
  setVoiceTarget,
  submitExecutorAudioInstruction,
  submitExecutorTextInstruction,
  updatePersona,
} from "./lib/session-client";
import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./lib/session-url";
import { buildBroCardModels, buildBroTaskRecords, buildBroThreadRecords } from "./components/newbro/adapters";
import { BroAvatar, avatarTypeToCharacter } from "./components/newbro/BroAvatar";
import { MarkdownText } from "./components/ui/markdown-text";
import { useNewbroShell } from "./NewbroShell";
import type { ExecutionRun, ExecutorNodeRecord, Persona, Task } from "./types";
import type { BroCardModel, BroTaskRecord, BroThreadRecord } from "./components/newbro/types";

type RuntimePage = "home" | "detail";
type HomeBroState = "working" | "idle" | "offline";

type HomeRecentItem = {
  id: string;
  title: string;
  bro: string;
  when: string;
};

type AudioTurnStatus = "recording" | "sending" | "sent" | "failed";
type TextTurnStatus = "sending" | "sent" | "failed";

type AudioTurn = {
  id: string;
  broId: string;
  threadId?: string | null;
  status: AudioTurnStatus;
  durationMs: number;
  createdAt?: string;
  timestampLabel?: string;
  error?: string;
  transcript?: string;
};

type TextTurn = {
  id: string;
  broId: string;
  threadId?: string | null;
  text: string;
  status: TextTurnStatus;
  createdAt?: string;
  timestampLabel?: string;
  error?: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  id: string;
  createdAt?: string;
};

type TimelineEntry =
  | { kind: "text"; id: string; timestamp?: string; turn: TextTurn; index: number }
  | { kind: "audio"; id: string; timestamp?: string; turn: AudioTurn; index: number }
  | { kind: "conversation"; id: string; timestamp?: string; message: ChatMessage; index: number }
  | { kind: "record"; id: string; timestamp?: string; record: BroTaskRecord; index: number };

const THREAD_LIST_PAGE_SIZE = 25;

function turnMatchesThread<T extends { threadId?: string | null }>(turn: T, threadId: string | null): boolean {
  return !threadId || !turn.threadId || turn.threadId === threadId;
}

type ActiveCodexAudioState = {
  enabled: boolean;
  reason: string;
};

type BroNodeState =
  | { kind: "sample" | "no_bound_node" | "bound_node_missing"; node: null }
  | { kind: "never_connected" | "usable_disconnected" | "usable_connected"; node: ExecutorNodeRecord };

function describeError(error: unknown, defaultMessage: string): string {
  return error instanceof Error && error.message.trim() ? error.message : defaultMessage;
}

function formatAudioDuration(durationMs: number): string {
  if (!durationMs) return "0:00";
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatMessageTimestamp(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return undefined;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function timelineTimestamp(value: string | undefined): number {
  if (!value) return Number.NEGATIVE_INFINITY;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function timelineKindOrder(kind: TimelineEntry["kind"]): number {
  if (kind === "text" || kind === "audio") return 0;
  if (kind === "record") return 1;
  return 2;
}

function buildTimelineEntries({
  records,
  textTurns,
  audioTurns,
  conversationMessages,
}: {
  records: BroTaskRecord[];
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  conversationMessages: ChatMessage[];
}): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...records.map((record, index) => ({
      kind: "record" as const,
      id: `record-${record.taskId}`,
      timestamp: record.timestamp,
      record,
      index,
    })),
    ...textTurns.map((turn, index) => ({
      kind: "text" as const,
      id: `text-${turn.id}`,
      timestamp: turn.createdAt,
      turn,
      index,
    })),
    ...audioTurns.map((turn, index) => ({
      kind: "audio" as const,
      id: `audio-${turn.id}`,
      timestamp: turn.createdAt,
      turn,
      index,
    })),
    ...conversationMessages.map((message, index) => ({
      kind: "conversation" as const,
      id: `conversation-${message.id}`,
      timestamp: message.createdAt,
      message,
      index,
    })),
  ];
  return entries.sort((left, right) => {
    const timeDelta = timelineTimestamp(left.timestamp) - timelineTimestamp(right.timestamp);
    if (timeDelta !== 0) return timeDelta;
    const kindDelta = timelineKindOrder(left.kind) - timelineKindOrder(right.kind);
    if (kindDelta !== 0) return kindDelta;
    return left.index - right.index;
  });
}

function MessageMeta({
  label,
  timestamp,
  error,
}: {
  label: string;
  timestamp?: string;
  error?: string;
}) {
  return (
    <>
      <span>{label}</span>
      {timestamp ? (
        <>
          <span> · </span>
          <span>{timestamp}</span>
        </>
      ) : null}
      {error ? (
        <>
          <span> · </span>
          <span>{error}</span>
        </>
      ) : null}
    </>
  );
}

function audioTurnMeta(turn: AudioTurn): string {
  const duration = formatAudioDuration(turn.durationMs);
  if (turn.status === "recording") return "Recording";
  if (turn.status === "sending") return `Sending · ${duration}`;
  if (turn.status === "failed") return `Failed · ${duration}`;
  return `Sent · ${duration}`;
}

function AudioTurnBubble({ bro, turn, mobile = false }: { bro: BroCardModel; turn: AudioTurn; mobile?: boolean }) {
  const prefix = mobile ? "thr" : "dt";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";
  return (
    <div className={`${prefix}-turn ${prefix}-turn-you`}>
      <div className={`${prefix}-bubble ${prefix}-bubble-you nb-audio-bubble nb-audio-bubble-${turn.status}`}>
        <span className="nb-audio-wave" aria-hidden="true">{[6, 13, 9, 16, 8, 15, 10, 14, 7].map((h, i) => <i key={i} style={{ height: `${h}px` }} />)}</span>
        <span className="nb-audio-label">{turn.status === "recording" ? "Recording…" : "Voice note"}</span>
        <span className="nb-audio-duration">{formatAudioDuration(turn.durationMs)}</span>
      </div>
      <div className={metaClass}>
        <MessageMeta
          label={audioTurnMeta(turn)}
          timestamp={turn.timestampLabel ?? formatMessageTimestamp(turn.createdAt)}
          error={turn.status === "failed" ? turn.error : undefined}
        />
      </div>
      {turn.transcript ? <div className="nb-audio-transcript">{turn.transcript}</div> : null}
      <span className="sr-only">
        Audio message to {bro.name}{turn.transcript ? `; transcript: ${turn.transcript}` : ""}.
      </span>
    </div>
  );
}

function TextTurnBubble({ turn, mobile = false }: { turn: TextTurn; mobile?: boolean }) {
  const prefix = mobile ? "thr" : "dt";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";
  const meta = turn.status === "sending" ? "Sending" : turn.status === "failed" ? "Failed" : "Sent";
  return (
    <div className={`${prefix}-turn ${prefix}-turn-you`}>
      <div className={`${prefix}-bubble ${prefix}-bubble-you${turn.status === "failed" ? " ob-bubble-failed" : ""}`}>{turn.text}</div>
      <div className={metaClass}>
        <MessageMeta
          label={meta}
          timestamp={turn.timestampLabel ?? formatMessageTimestamp(turn.createdAt)}
          error={turn.status === "failed" ? turn.error : undefined}
        />
      </div>
    </div>
  );
}

function normalizeUserTurnText(value: string | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function syncedUserTextAlreadyVisible(record: BroTaskRecord, textTurns: TextTurn[], audioTurns: AudioTurn[]): boolean {
  const userText = normalizeUserTurnText(record.userText);
  if (!userText) return true;
  return textTurns.some((turn) => normalizeUserTurnText(turn.text) === userText)
    || audioTurns.some((turn) => normalizeUserTurnText(turn.transcript) === userText);
}

function SyncedTaskRecordTurn({
  bro,
  record,
  textTurns,
  audioTurns,
  mobile = false,
}: {
  bro: BroCardModel;
  record: BroTaskRecord;
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  mobile?: boolean;
}) {
  const showUserTurn = Boolean(record.userText) && !syncedUserTextAlreadyVisible(record, textTurns, audioTurns);
  return (
    <>
      {showUserTurn ? (
        <TextTurnBubble
          turn={{
            id: `synced-user-${record.taskId}`,
            broId: bro.id,
            text: record.userText ?? "",
            status: "sent",
            timestampLabel: record.timestampLabel,
          }}
          mobile={mobile}
        />
      ) : null}
      <TaskRecordCard bro={bro} record={record} mobile={mobile} />
    </>
  );
}

function taskRecordIsActive(record: BroTaskRecord): boolean {
  return !["completed", "failed", "cancelled", "paused"].includes(record.status);
}

function TaskRecordCard({ bro, record, mobile = false }: { bro: BroCardModel; record: BroTaskRecord; mobile?: boolean }) {
  const active = taskRecordIsActive(record);
  const prefix = mobile ? "thr" : "dt";
  const statusClass = mobile ? "thr-status" : "dt-status";
  const doneClass = mobile ? "thr-status-done" : "dt-status-done";
  const spinClass = mobile ? "thr-status-spin" : "dt-status-spin";
  const doneDotClass = mobile ? "thr-status-done-dot" : "dt-status-done-dot";
  const titleClass = mobile ? "thr-status-title" : "dt-status-title";
  const pctClass = mobile ? "thr-status-pct" : "dt-status-pct";
  const barClass = mobile ? "thr-status-bar" : "dt-status-bar";
  const footClass = mobile ? "thr-status-foot" : "dt-status-foot";
  const bodyText = record.summary || record.description || bro.progressLabel;
  return (
    <div className={`${prefix}-turn ${prefix}-turn-bro`}>
      <div className={`${statusClass}${active ? "" : ` ${doneClass}`}`}>
        <div className={`${statusClass}-head`}>
          {active ? <span className={spinClass} /> : <span className={doneDotClass} />}
          <span className={titleClass}>{record.title}</span>
          <span className={pctClass}>
            <MessageMeta label={record.statusLabel} timestamp={record.timestampLabel} />
          </span>
        </div>
        <div className={barClass}><i style={{ width: `${Math.max(8, Math.min(100, Math.round(record.progress)))}%` }} /></div>
        <div className={`${footClass} ${prefix}-task-body`}>
          <MarkdownText>{bodyText}</MarkdownText>
        </div>
      </div>
    </div>
  );
}

function ConversationMessageBubble({ bro, message, mobile = false }: { bro: BroCardModel; message: ChatMessage; mobile?: boolean }) {
  const prefix = mobile ? "thr" : "dt";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";
  const isUser = message.role === "user";
  return (
    <div className={`${prefix}-turn ${isUser ? `${prefix}-turn-you` : `${prefix}-turn-bro`}`}>
      <div className={`${prefix}-bubble ${isUser ? `${prefix}-bubble-you` : `${prefix}-bubble-bro`}`}>{message.text}</div>
      <div className={metaClass}>
        <MessageMeta label={isUser ? "You" : bro.name} timestamp={formatMessageTimestamp(message.createdAt)} />
      </div>
    </div>
  );
}

function applyAudioTranscripts(turns: AudioTurn[], runs: ExecutionRun[]): AudioTurn[] {
  if (turns.length === 0) return turns;
  const transcripts = new Map<string, string>();
  for (const run of runs) {
    const stickyTranscripts = run.metadata?.audio_transcripts;
    if (stickyTranscripts && typeof stickyTranscripts === "object" && !Array.isArray(stickyTranscripts)) {
      for (const [audioId, transcript] of Object.entries(stickyTranscripts as Record<string, unknown>)) {
        if (typeof transcript === "string" && audioId && transcript.trim()) {
          transcripts.set(audioId, transcript.trim());
        }
      }
    }
    const event = run.metadata?.latest_progress_event;
    if (!event || typeof event !== "object" || Array.isArray(event)) continue;
    const metadata = event as Record<string, unknown>;
    const audioId = metadata.source_audio_instruction_id;
    const transcript = metadata.transcript_text;
    if (typeof audioId === "string" && audioId && typeof transcript === "string" && transcript.trim()) {
      transcripts.set(audioId, transcript.trim());
    }
  }
  if (transcripts.size === 0) return turns;
  let changed = false;
  const next = turns.map((turn) => {
    const transcript = transcripts.get(turn.id);
    if (!transcript || turn.transcript === transcript) return turn;
    changed = true;
    return { ...turn, transcript };
  });
  return changed ? next : turns;
}

function activeCodexAudioState(
  shell: Pick<ReturnType<typeof useNewbroShell>, "runtimePersonas" | "tasks" | "executionSessions" | "executionRuns" | "executorNodes">,
  bro: BroCardModel,
): ActiveCodexAudioState {
  const persona = shell.runtimePersonas.find((candidate) => candidate.persona_id === bro.id);
  if (!persona?.executor_node_id) return { enabled: false, reason: "Bind and connect this Bro before recording." };
  const node = shell.executorNodes.find((candidate) => candidate.node_id === persona.executor_node_id);
  if (!node || node.connection_status !== "connected" || !node.connected_executors.includes("codex")) {
    return { enabled: false, reason: "Connect the Codex executor before recording." };
  }
  const codexCapability = node.connected_executor_capabilities?.find(
    (capability) => capability.executor_type === "codex",
  );
  if (codexCapability && !codexCapability.supports_audio_instruction) {
    return { enabled: false, reason: "Enable local Whisper on the executor node before recording." };
  }
  if (!persona.current_task_id) return { enabled: true, reason: "Hold to record audio" };
  const currentTask = shell.tasks.find((task) => task.task_id === persona.current_task_id);
  if (currentTask && ["created", "queued"].includes(currentTask.status)) {
    return { enabled: true, reason: "Hold to record audio" };
  }
  const activeRun = shell.executionRuns.find((run) => (
    run.task_id === persona.current_task_id
    && run.executor_type === "codex"
    && ["assigned", "running", "blocked"].includes(run.status)
  ));
  if (!activeRun) return { enabled: false, reason: "No active Codex session for this Bro." };
  const activeSession = shell.executionSessions.find((session) => (
    session.base_executor_id === "codex"
    && session.active_run_id === activeRun.run_id
  ));
  if (!activeSession) return { enabled: false, reason: "No active Codex session for this Bro." };
  return { enabled: true, reason: "Hold to record audio" };
}

function activeCodexTextState(
  shell: Pick<ReturnType<typeof useNewbroShell>, "runtimePersonas" | "tasks" | "executionSessions" | "executionRuns" | "executorNodes">,
  bro: BroCardModel,
): ActiveCodexAudioState {
  const persona = shell.runtimePersonas.find((candidate) => candidate.persona_id === bro.id);
  if (!persona?.executor_node_id) return { enabled: false, reason: "Bind and connect this Bro before sending." };
  const node = shell.executorNodes.find((candidate) => candidate.node_id === persona.executor_node_id);
  if (!node || node.connection_status !== "connected" || !node.connected_executors.includes("codex")) {
    return { enabled: false, reason: "Connect the Codex executor before sending." };
  }
  const codexCapability = node.connected_executor_capabilities?.find(
    (capability) => capability.executor_type === "codex",
  );
  if (codexCapability && !codexCapability.supports_follow_up) {
    return { enabled: false, reason: "Selected Bro's executor node does not support text follow-up." };
  }
  if (!persona.current_task_id) return { enabled: true, reason: "Start a direct executor task" };
  const currentTask = shell.tasks.find((task) => task.task_id === persona.current_task_id);
  if (currentTask && ["created", "queued"].includes(currentTask.status)) {
    return { enabled: true, reason: "Start queued executor task" };
  }
  const activeRun = shell.executionRuns.find((run) => (
    run.task_id === persona.current_task_id
    && run.executor_type === "codex"
    && ["assigned", "running", "blocked"].includes(run.status)
  ));
  if (!activeRun) return { enabled: false, reason: "No active Codex session for this Bro." };
  const activeSession = shell.executionSessions.find((session) => (
    session.base_executor_id === "codex"
    && session.active_run_id === activeRun.run_id
  ));
  if (!activeSession) return { enabled: false, reason: "No active Codex session for this Bro." };
  return { enabled: true, reason: "Send directly to executor" };
}

function usePushToTalkAudio({
  sessionId,
  broId,
  targetThreadId,
  disabled,
  onTurn,
  onRemoveTurn,
  onError,
  onSent,
}: {
  sessionId: string | null;
  broId: string;
  targetThreadId: string | null;
  disabled: boolean;
  onTurn: (turn: AudioTurn) => void;
  onRemoveTurn: (turnId: string) => void;
  onError: (message: string) => void;
  onSent: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "recording" | "sending">("idle");
  const activeRef = useRef<{
    recorder: MediaRecorder;
    stream: MediaStream;
    chunks: Blob[];
    startedAt: number;
    createdAt: string;
    turnId: string;
  } | null>(null);

  async function start() {
    if (disabled || !sessionId || activeRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      const turnId = `audio-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const active = {
        recorder,
        stream,
        chunks: [] as Blob[],
        startedAt: Date.now(),
        createdAt: new Date().toISOString(),
        turnId,
      };
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) active.chunks.push(event.data);
      });
      activeRef.current = active;
      onTurn({ id: turnId, broId, threadId: targetThreadId, status: "recording", durationMs: 0, createdAt: active.createdAt });
      setPhase("recording");
      recorder.start();
    } catch (error: unknown) {
      onError(describeError(error, "Microphone could not be started."));
    }
  }

  async function stopAndSend() {
    const active = activeRef.current;
    if (!active || !sessionId) return;
    activeRef.current = null;
    setPhase("sending");
    const durationMs = Math.max(1, Date.now() - active.startedAt);
    const blob = await stopRecorder(active);
    try {
      const pcm = await mediaBlobToPcm16(blob);
      onTurn({ id: active.turnId, broId, threadId: targetThreadId, status: "sending", durationMs: pcm.durationMs || durationMs, createdAt: active.createdAt });
      const response = await submitExecutorAudioInstruction(sessionId, {
        targetPersonaId: broId,
        targetThreadId,
        pcm16: pcm.blob,
        durationMs: pcm.durationMs || durationMs,
        sampleRate: pcm.sampleRate,
        numChannels: pcm.numChannels,
        samplesPerChannel: pcm.samplesPerChannel,
      });
      onRemoveTurn(active.turnId);
      onTurn({
        id: response.audio_instruction_id,
        broId,
        threadId: response.target_thread_id ?? targetThreadId,
        status: "sent",
        durationMs: pcm.durationMs || durationMs,
        createdAt: active.createdAt,
        transcript: response.transcript_text?.trim() || undefined,
      });
      onSent();
    } catch (error: unknown) {
      const message = describeError(error, "Audio could not be sent.");
      onTurn({ id: active.turnId, broId, threadId: targetThreadId, status: "failed", durationMs, createdAt: active.createdAt, error: message });
      onError(message);
    } finally {
      setPhase("idle");
    }
  }

  function cancel() {
    const active = activeRef.current;
    if (!active) return;
    activeRef.current = null;
    void stopRecorder(active).catch(() => undefined);
    onRemoveTurn(active.turnId);
    setPhase("idle");
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") cancel();
    }
    function onVisibilityChange() {
      if (document.visibilityState === "hidden") cancel();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("blur", cancel);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("blur", cancel);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      cancel();
    };
  }, []);

  return { phase, start, stopAndSend, cancel };
}

async function stopRecorder(active: {
  recorder: MediaRecorder;
  stream: MediaStream;
  chunks: Blob[];
}): Promise<Blob> {
  if (active.recorder.state !== "inactive") {
    const stopped = new Promise<void>((resolve) => {
      active.recorder.addEventListener("stop", () => resolve(), { once: true });
    });
    active.recorder.stop();
    await stopped;
  }
  active.stream.getTracks().forEach((track) => track.stop());
  return new Blob(active.chunks, { type: active.recorder.mimeType });
}

async function mediaBlobToPcm16(blob: Blob): Promise<{
  blob: Blob;
  durationMs: number;
  sampleRate: number;
  numChannels: number;
  samplesPerChannel: number;
}> {
  const audioContextConstructor = window.AudioContext
    ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!audioContextConstructor) {
    throw new Error("This browser cannot decode recorded audio.");
  }
  const audioContext = new audioContextConstructor();
  try {
    const decoded = await audioContext.decodeAudioData(await blob.arrayBuffer());
    const samplesPerChannel = decoded.length;
    const mixed = new Float32Array(samplesPerChannel);
    for (let channelIndex = 0; channelIndex < decoded.numberOfChannels; channelIndex += 1) {
      const channel = decoded.getChannelData(channelIndex);
      for (let sampleIndex = 0; sampleIndex < samplesPerChannel; sampleIndex += 1) {
        mixed[sampleIndex] += channel[sampleIndex] / decoded.numberOfChannels;
      }
    }
    const pcm16 = new Int16Array(samplesPerChannel);
    for (let index = 0; index < samplesPerChannel; index += 1) {
      const sample = Math.max(-1, Math.min(1, mixed[index]));
      pcm16[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return {
      blob: new Blob([pcm16.buffer], { type: "audio/pcm" }),
      durationMs: Math.round(decoded.duration * 1000),
      sampleRate: decoded.sampleRate,
      numChannels: 1,
      samplesPerChannel,
    };
  } finally {
    void audioContext.close();
  }
}

function hasNodeEverConnected(node: ExecutorNodeRecord): boolean {
  return Boolean(node.last_connected_at);
}

function deriveBroNodeState(bro: BroCardModel | null, nodes: ExecutorNodeRecord[]): BroNodeState {
  if (!bro || bro.source !== "runtime") return { kind: "sample", node: null };
  if (!bro.executorNodeId) return { kind: "no_bound_node", node: null };
  const node = nodes.find((candidate) => candidate.node_id === bro.executorNodeId) ?? null;
  if (!node) return { kind: "bound_node_missing", node: null };
  if (!hasNodeEverConnected(node)) return { kind: "never_connected", node };
  if (node.connection_status === "connected") return { kind: "usable_connected", node };
  return { kind: "usable_disconnected", node };
}

function nodeStateNeedsConnect(state: BroNodeState): boolean {
  return state.kind === "no_bound_node" || state.kind === "bound_node_missing" || state.kind === "never_connected";
}

function homeBroState(bro: BroCardModel): HomeBroState {
  if (bro.status === "busy") return "working";
  if (bro.liveState === "offline" || bro.liveState === "unbound") return "offline";
  return "idle";
}

function homeBroTone(state: HomeBroState): "info" | "calm" | "warn" {
  if (state === "working") return "info";
  if (state === "offline") return "warn";
  return "calm";
}

function homeBroChipLabel(state: HomeBroState): string {
  if (state === "working") return "WORKING";
  if (state === "offline") return "OFFLINE";
  return "STANDING BY";
}

function homeBroNode(bro: BroCardModel): string {
  if (bro.nodeName) return bro.nodeName;
  if (bro.liveState === "unbound") return "no node";
  return "local node";
}

function homeBroLast(bro: BroCardModel, state: HomeBroState): string {
  if (state === "working") return bro.progressLabel || `${Math.round(bro.progress)}%`;
  if (state === "offline") return bro.nodeName ? `${bro.nodeName} offline` : "needs node";
  return bro.liveState === "live" ? "ready now" : "standing by";
}

function homeBroSortRank(bro: BroCardModel): number {
  const state = homeBroState(bro);
  if (state === "working") return 0;
  if (bro.liveState === "live") return 1;
  if (state === "offline") return 3;
  return 2;
}

function compareHomeBros(a: BroCardModel, b: BroCardModel): number {
  const rankDelta = homeBroSortRank(a) - homeBroSortRank(b);
  if (rankDelta !== 0) return rankDelta;
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id.localeCompare(b.id);
}

function broDetailHref(broId: string): string {
  if (typeof window === "undefined") return `/bros/${encodeURIComponent(broId)}`;
  const sid = new URLSearchParams(window.location.search).get("sid");
  const query = sid ? `?sid=${encodeURIComponent(sid)}` : "";
  return `/bros/${encodeURIComponent(broId)}${query}`;
}

function openBroFromHome(event: MouseEvent<HTMLAnchorElement>, broId: string, onOpen: (id: string) => void): void {
  if (
    event.defaultPrevented
    || event.button !== 0
    || event.metaKey
    || event.altKey
    || event.ctrlKey
    || event.shiftKey
  ) {
    return;
  }
  event.preventDefault();
  onOpen(broId);
}

function taskTimeLabel(task: Task): string {
  const value = ["updated_at", "completed_at", "created_at"]
    .map((key) => task.metadata[key])
    .find((candidate): candidate is string => typeof candidate === "string" && candidate.trim().length > 0);
  if (!value) return task.status.replace(/_/g, " ");
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return task.status.replace(/_/g, " ");
  const minutes = Math.floor(Math.max(0, Date.now() - timestamp) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function buildHomeRecents(tasks: Task[], personas: Persona[]): HomeRecentItem[] {
  const personaNameById = new Map(personas.map((persona) => [persona.persona_id, persona.name]));
  return [...tasks].reverse().slice(0, 5).map((task) => {
    const personaId = task.metadata.persona_id ?? task.metadata.assigned_bro_id;
    const bro = typeof personaId === "string" ? (personaNameById.get(personaId) ?? "NewBro") : "NewBro";
    return { id: task.task_id, title: task.title, bro, when: taskTimeLabel(task) };
  });
}

function Header({
  active,
  bro,
  onHome,
  onLogout,
  account,
  nodeCount,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  onHome: () => void;
  onLogout: () => void;
  account: string;
  nodeCount: number;
}) {
  const tone = bro ? homeBroTone(homeBroState(bro)) : nodeCount > 0 ? "calm" : "warn";
  const detailPaused = bro?.liveState === "offline" || bro?.liveState === "unbound";
  return (
    <header className="dt-header" data-testid="newbro-sidebar">
      <div className="dt-header-l">
        <button type="button" className="dt-header-brand border-0 bg-transparent p-0" onClick={onHome}>
          <div className="dt-header-brand-tile">
            <img src="/newbro.webp" alt="" draggable={false} />
          </div>
          <span className="dt-header-brand-name">newbro</span>
        </button>
        {bro ? (
          <>
            <span className="dt-header-sep" />
            <button type="button" className={`dt-header-broswitch dt-header-broswitch-${tone}`} onClick={onHome}>
              <span className="dt-header-broswitch-avatar">
                <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={homeBroState(bro)} size={22} />
                <span className="dt-header-broswitch-pip" />
              </span>
              <span>{bro.name}</span>
            </button>
          </>
        ) : null}
      </div>
      <div className="dt-header-r">
        <span className={`dt-header-pill ${bro ? (detailPaused ? "dt-header-pill-paused" : "dt-header-pill-live") : nodeCount > 0 ? "dt-header-pill-ready" : "dt-header-pill-empty"}`}>
          <span className="dt-header-pill-dot" />
          {bro ? (detailPaused ? "paused · node offline" : "live · listening") : nodeCount > 0 ? "runtime ready" : "setup needed"}
        </span>
        <span className="dt-header-account dt-header-static">
          <span className="dt-header-account-avatar">{account.trim().charAt(0).toUpperCase() || "N"}</span>
          <span className="dt-header-account-name">{account}</span>
        </span>
        <button type="button" data-testid="sidebar-logout" className="dt-header-icon-btn" aria-label="Sign out" onClick={onLogout}>
          <LogOut className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
      </div>
    </header>
  );
}

function DesktopFrame({
  active,
  bro,
  children,
  onHome,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  children: React.ReactNode;
  onHome: () => void;
}) {
  const shell = useNewbroShell();
  return (
    <div className="dt-frame min-h-dvh">
      <div className="dt-shell min-h-dvh">
        <Header
          active={active}
          bro={bro}
          onHome={onHome}
          nodeCount={shell.executorNodes.filter((node) => Boolean(node.last_connected_at)).length}
          account={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
          onLogout={() => { void shell.logout(); }}
        />
        <main className="dt-main" data-testid="newbro-shell">
          {children}
        </main>
      </div>
    </div>
  );
}

function StateChip({ state }: { state: HomeBroState }) {
  const tone = homeBroTone(state);
  return (
    <span className={`dt-home-chip dt-home-chip-${tone}`}>
      <span className="dt-home-chip-dot" />
      {homeBroChipLabel(state)}
    </span>
  );
}

function DesktopBroCard({ bro, onOpen, featured = false }: { bro: BroCardModel; onOpen: (id: string) => void; featured?: boolean }) {
  const state = homeBroState(bro);
  const tone = homeBroTone(state);
  const progress = Math.max(5, Math.min(100, Math.round(bro.progress)));
  return (
    <a data-testid={`bro-card-${bro.id}`} className={`dt-bro-card dt-bro-card-${tone}${featured ? " dt-bro-card-featured" : ""}`} href={broDetailHref(bro.id)} onClick={(event) => openBroFromHome(event, bro.id, onOpen)}>
      <div className={`dt-bro-card-avatar dt-bro-card-avatar-${tone}`}>
        <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={42} />
        <span className={`dt-bro-card-pip dt-bro-card-pip-${tone}`} />
      </div>
      <div className="dt-bro-card-body">
        <div className="dt-bro-card-row">
          <span className="dt-bro-card-name">{bro.name}</span>
          <StateChip state={state} />
        </div>
        <div className="dt-bro-card-meta">
          <span className="dt-bro-card-mono">on {bro.executorNodeId ? "codex" : "setup"}</span>
          <span className="dt-bro-meta-sep">·</span>
          <span className="dt-bro-card-mono">{homeBroNode(bro)}</span>
          <span className="dt-bro-meta-sep">·</span>
          <span>{homeBroLast(bro, state)}</span>
        </div>
        <div className={`dt-bro-card-task${state === "working" ? " dt-bro-card-task-running" : ""}`}>
          {state === "working" ? <span className="dt-bro-card-spin" /> : null}
          <span className="dt-bro-card-task-text">{state === "working" ? bro.taskTitle : bro.idleNote}</span>
          {state === "working" ? <span className="dt-bro-card-pct">{progress}%</span> : null}
        </div>
        {state === "working" ? (
          <div className="dt-bro-card-bar"><span className="dt-bro-card-bar-fill" style={{ width: `${progress}%` }} /></div>
        ) : null}
      </div>
      <span className="dt-bro-card-arrow">›</span>
    </a>
  );
}

function DesktopRosterRow({ bro, onOpen }: { bro: BroCardModel; onOpen: (id: string) => void }) {
  const state = homeBroState(bro);
  return (
    <a data-testid={`bro-card-${bro.id}`} className={`dt-roster-row dt-roster-row-${state}`} href={broDetailHref(bro.id)} onClick={(event) => openBroFromHome(event, bro.id, onOpen)}>
      <div className={`dt-roster-avatar dt-roster-avatar-${state}`}>
        <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={26} />
      </div>
      <span className="dt-roster-name">{bro.name}</span>
      <span className="dt-roster-last">{homeBroLast(bro, state)}</span>
    </a>
  );
}

function EmptyWorkspace({ onCreate }: { onCreate: () => void }) {
  return (
    <section className="dt-empty-stage" data-testid="empty-workspace">
      <div className="dt-empty-art-lg" aria-hidden="true">
        <div className="dt-empty-grid-lg">
          {Array.from({ length: 80 }).map((_, index) => (
            <i key={index} style={{ animationDelay: `${(index % 9) * 0.12}s` }} />
          ))}
        </div>
        <div className="dt-empty-mascot-lg"><img src="/newbro.webp" alt="" draggable={false} /></div>
        <span className="dt-empty-zzz-lg" aria-hidden="true"><i>z</i><i>z</i><i>z</i></span>
      </div>
      <div className="dt-empty-copy">
        <span className="ob-eyebrow ob-eyebrow-coral">YOUR CREW · 0 BROS</span>
        <h1 className="dt-empty-h-lg">You don't have a bro yet.</h1>
        <p className="dt-empty-sub-lg">
          A <strong>bro</strong> is a worker persona bound to an executor on one of your machines. Create one, connect a node, and they'll start working alongside you.
        </p>
        <div className="dt-empty-actions-lg">
          <button type="button" className="ob-cta dt-empty-cta-lg" onClick={onCreate}>
            <Plus size={15} strokeWidth={2.4} aria-hidden="true" />
            <span>Create your first bro</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function DesktopHome({ onOpenBro }: { onOpenBro: (id: string) => void }) {
  const shell = useNewbroShell();
  const [sheetOpen, setSheetOpen] = useState(false);
  const homeBros = useMemo(() => [...shell.bros].sort(compareHomeBros), [shell.bros]);
  const workingBros = homeBros.filter((bro) => homeBroState(bro) === "working");
  const standingByBros = homeBros.filter((bro) => homeBroState(bro) !== "working");
  const recents = buildHomeRecents(shell.tasks, shell.runtimePersonas);
  const hasBros = shell.runtimePersonas.length > 0;

  if (!shell.hasLoadedShellSnapshot) return null;

  return (
    <DesktopFrame active="home" onHome={() => undefined}>
      {!hasBros ? (
        <EmptyWorkspace onCreate={() => setSheetOpen(true)} />
      ) : (
        <div className="dt-main-pad dt-home-pad">
          <div className="dt-home-grid">
            <section className="dt-home-main">
              <header className="dt-page-head">
                <div>
                  <h1 className="dt-page-title">Home</h1>
                  <p className="dt-page-sub">Hold space anywhere, talk to any bro, or open one to read their thread. Sessions persist as long as the node stays online.</p>
                </div>
                <div className="dt-page-actions">
                  <button type="button" className="dt-page-action dt-page-action-primary" onClick={() => setSheetOpen(true)}>
                    <Plus size={14} aria-hidden="true" />
                    <span>New bro</span>
                  </button>
                </div>
              </header>
              <>
                {workingBros.length > 0 ? (
                  <section className="dt-home-section">
                    <div className="dt-home-section-head">
                      <span className="ob-eyebrow ob-eyebrow-coral">IN FLIGHT · {workingBros.length}</span>
                      <span className="dt-home-section-sub">Sessions currently dispatched</span>
                    </div>
                    <div className="dt-bro-grid">
                      {workingBros.map((bro) => <DesktopBroCard key={bro.id} bro={bro} featured onOpen={onOpenBro} />)}
                    </div>
                  </section>
                ) : null}
                <section className="dt-home-section">
                  <div className="dt-home-section-head">
                    <span className="ob-eyebrow">STANDING BY · {standingByBros.length}</span>
                    <span className="dt-home-section-sub">Quiet for now - hold space to wake one</span>
                  </div>
                  <div className="dt-bro-roster">
                    {standingByBros.map((bro) => <DesktopRosterRow key={bro.id} bro={bro} onOpen={onOpenBro} />)}
                  </div>
                </section>
              </>
            </section>
            <aside className="dt-home-rail">
              <section className="dt-rail-block">
                <div className="dt-rail-block-head">
                  <span className="ob-eyebrow">RECENT</span>
                  <button type="button" className="ob-link ob-link-sm">See all</button>
                </div>
                {recents.length > 0 ? (
                  <ul className="dt-recent-list">
                    {recents.map((recent) => (
                      <li key={recent.id}>
                        <div className="dt-recent">
                          <span className="dt-recent-icon"><FileText size={14} strokeWidth={1.9} /></span>
                          <span className="dt-recent-body">
                            <span className="dt-recent-title">{recent.title}</span>
                            <span className="dt-recent-meta"><span>{recent.bro}</span><span className="dt-bro-meta-sep">·</span><span>{recent.when}</span></span>
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="dt-art-empty">Threads will appear here after your bros start reporting back.</div>
                )}
              </section>
            </aside>
          </div>
        </div>
      )}
      {sheetOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSheetOpen(false)} onCreated={shell.refreshShellSession} />
      ) : null}
    </DesktopFrame>
  );
}

function CreateConnectSheet({
  sessionId,
  onClose,
  onCreated,
  bro,
}: {
  sessionId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
  bro?: BroCardModel | null;
}) {
  const [name, setName] = useState(bro?.name ?? "atlas");
  const [command, setCommand] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pendingNodeId, setPendingNodeId] = useState<string | null>(null);
  const [pendingBroName, setPendingBroName] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const finalizingRef = useRef(false);
  const trimmedName = name.trim();
  const canCreate = trimmedName.length > 0 && !busy && !command && !pendingNodeId && !completed;

  async function copyCommand(value: string) {
    await navigator.clipboard?.writeText(value).then(() => setCopied(true), () => setCopied(false));
  }

  async function finalizeConnectedNode(nodeId: string, broName: string) {
    if (finalizingRef.current) return;
    finalizingRef.current = true;
    try {
      if (bro?.source === "runtime" && !bro.executorNodeId) {
        await updatePersona(sessionId, bro.id, { executor_node_id: nodeId });
      } else if (!bro) {
        await createPersona(sessionId, {
          name: broName,
          avatar: "bro",
          base_prompt: "Execute direct typed and push-to-talk instructions in the connected workspace.",
          executor_node_id: nodeId,
        });
      }
      setCompleted(true);
      setPendingNodeId(null);
      setError(null);
      await onCreated();
    } catch (err) {
      finalizingRef.current = false;
      setError(describeError(err, "Could not finish creating this Bro after the node connected."));
    }
  }

  async function createAndConnect() {
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      const nextBroName = trimmedName;
      const issue = bro?.executorNodeId
        ? await revealExecutorNodeConnectCommand(sessionId, bro.executorNodeId)
        : await createExecutorNode(sessionId, { name: `${nextBroName} local node`, enabled_executors: ["codex"] });
      const nextCommand = buildExecutorRunCommand(issue.node.node_id, issue.token, {
        enabledExecutors: issue.node.enabled_executors,
        acpxAgent: issue.node.acpx_agent,
      });
      setCommand(nextCommand);
      setPendingNodeId(issue.node.last_connected_at ? null : issue.node.node_id);
      setPendingBroName(nextBroName);
      setCompleted(false);
      await copyCommand(nextCommand);
      await onCreated();
      if (issue.node.last_connected_at) {
        await finalizeConnectedNode(issue.node.node_id, nextBroName);
      }
    } catch (err) {
      setError(describeError(err, "Could not create and connect this Bro."));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!pendingNodeId || !pendingBroName || completed) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const snapshot = await getSessionSnapshot(sessionId);
        const node = snapshot.executor_nodes.find((candidate) => candidate.node_id === pendingNodeId);
        if (node?.last_connected_at) {
          if (!cancelled) {
            await finalizeConnectedNode(pendingNodeId, pendingBroName);
          }
          return;
        }
        if (!cancelled) {
          timer = setTimeout(poll, 1500);
        }
      } catch (err) {
        if (!cancelled) {
          setError(describeError(err, "Waiting for the node to connect before creating this Bro."));
          timer = setTimeout(poll, 3000);
        }
      }
    };

    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [bro, completed, onCreated, pendingBroName, pendingNodeId, sessionId]);

  return (
    <div className="nb-first-run-sheet-layer" role="dialog" aria-modal="true" aria-label="Create and connect a Bro">
      <div className="nb-first-run-sheet-frame ob-firsthome-sheet">
        <div className="ob-sheet-dim" onClick={onClose} aria-hidden="true" />
        <section className="ob-sheet nb-create-connect-modal">
          <div className="ob-sheet-handle" aria-hidden="true" />
          <header className="ob-sheet-head">
            <div className="ob-sheet-titles">
              <span className="ob-eyebrow ob-eyebrow-coral">NEW BRO</span>
              <h2 className="ob-sheet-h">Name it, then connect a node.</h2>
            </div>
            <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}><X size={16} strokeWidth={2.2} /></button>
          </header>
          <div className="ob-sheet-body">
            <div className="dt-modal-cols nb-create-connect-cols">
              <div className="dt-modal-col">
                <div className="ob-fieldset">
                  <label className="ob-field">
                    <span className="ob-field-eyebrow">NAME</span>
                    <div className="ob-input ob-input-filled">
                      <span className="ob-input-prefix">@</span>
                      <input type="text" value={name} disabled={Boolean(bro) || Boolean(command) || busy} onChange={(event) => setName(event.target.value)} />
                    </div>
                    <span className="ob-field-hint">One word, easy to say out loud. e.g. atlas, scout, forge, muse.</span>
                  </label>
                </div>
                <div className="ob-fieldset">
                  <span className="ob-field-eyebrow ob-fieldset-eyebrow">EXECUTOR</span>
                  <div className="ob-exec-grid">
                    <div className="ob-exec-card ob-exec-card-on">
                      <span className="ob-exec-name">Codex</span>
                      <span className="ob-exec-desc">Long-running agent · shell + browser</span>
                      <span className="ob-exec-check" aria-hidden="true"><Check size={11} strokeWidth={2.8} /></span>
                    </div>
                    <div className="ob-exec-card" aria-disabled="true">
                      <span className="ob-exec-name">Hermes</span>
                      <span className="ob-exec-desc">Headless · ops + scripts</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="dt-modal-col">
                <div className="ob-fieldset">
                  <div className="ob-fieldset-eyebrow-row">
                    <span className="ob-field-eyebrow">CONNECT A NODE</span>
                    <span className="ob-fieldset-eyebrow-meta">{completed ? "connected" : command ? "ready" : "on demand"}</span>
                  </div>
                  <div className="ob-connect">
                    <div className="ob-connect-cmd">
                      <span className="ob-connect-prompt">$</span>
                      <span className="ob-connect-line">
                        {command ? command : <>newbro executor run <span className="ob-connect-tok">--token pending</span></>}
                      </span>
                      <button type="button" className="ob-connect-copy" aria-label="Copy command" disabled={!command} onClick={() => { if (command) void copyCommand(command); }}>
                        {copied ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.9} />}
                      </button>
                    </div>
                    <div className="ob-connect-status">
                      <span className="ob-connect-spinner" aria-hidden="true"><span /><span /><span /></span>
                      <span className="ob-connect-status-text">
                        <strong>{completed ? `${pendingBroName || trimmedName} is connected.` : command ? `Listening for ${pendingBroName || trimmedName}...` : `Ready to connect ${trimmedName || "a Bro"}...`}</strong>
                        <span>{completed ? "The Bro has been created after the node connected successfully." : command ? `Run that command on the machine where ${pendingBroName || trimmedName} should work. The Bro appears after the first successful connection.` : "Newbro will issue a node command first. The Bro appears after the first successful connection."}</span>
                      </span>
                      <span className="ob-connect-time">{completed ? "done" : copied ? "copied" : command ? "ready" : "new"}</span>
                    </div>
                  </div>
                  <div className="ob-connect-meta">
                    <span>Real node credential flow</span>
                    <span className="ob-connect-meta-sep">·</span>
                    <span>First successful connection creates the Bro</span>
                  </div>
                </div>
                <div className="dt-modal-tip">
                  <span className="dt-modal-tip-eyebrow">TIP</span>
                  <p>
                    The node is just a long-running process. It can sit on a Mac mini,
                    a workshop laptop, or any always-on box. You can rebind {pendingBroName || trimmedName || "this Bro"} later.
                  </p>
                </div>
              </div>
            </div>
            {error ? <div className="nb-status-banner nb-status-banner-error">{error}</div> : null}
          </div>
          <footer className="ob-sheet-foot">
            <span className="dt-modal-foot-status nb-create-connect-foot-status">
              <span className="dt-modal-foot-dot" />
              {completed ? "Connected once · Bro ready" : command ? "Waiting for first node connection" : "Command will be generated on demand"}
            </span>
            {command && completed ? (
              <button type="button" data-testid="bro-setup-done" className="ob-cta ob-cta-block" onClick={() => { void onCreated().finally(onClose); }}>
                Done
              </button>
            ) : (
              <button type="button" data-testid="bro-setup-create-node" className={`ob-cta ob-cta-block${busy ? " ob-cta-pending" : ""}`} disabled={!canCreate} onClick={() => { void createAndConnect(); }}>
                {busy ? <span className="ob-cta-spinner" aria-hidden="true" /> : null}
                <span>{busy ? "Preparing..." : command ? "Waiting for first connection..." : "Create and connect"}</span>
              </button>
            )}
          </footer>
        </section>
      </div>
    </div>
  );
}

function OfflineBanner({ bro, node, sessionId }: { bro: BroCardModel; node: ExecutorNodeRecord; sessionId: string | null }) {
  const [command, setCommand] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  async function reveal() {
    if (!sessionId || bro.source !== "runtime") return;
    const issue = await revealExecutorNodeConnectCommand(sessionId, node.node_id);
    const next = buildExecutorRunCommand(issue.node.node_id, issue.token, {
      enabledExecutors: issue.node.enabled_executors,
      acpxAgent: issue.node.acpx_agent,
    });
    setCommand(next);
    await navigator.clipboard?.writeText(next).then(() => setCopied(true), () => setCopied(false));
  }
  return (
    <section data-testid="bro-node-disconnected-warning" className="ob-offline-banner dt-offline-banner nb-artboard-offline">
      <span className="ob-offline-banner-icon" aria-hidden="true">
        <WifiOff size={16} strokeWidth={2} />
      </span>
      <div className="ob-offline-banner-body">
        <strong>{node.name} is not connected.</strong>
        <span>{bro.name} can't take new messages until the node reconnects. The current draft stays saved.</span>
        {command ? <pre className="nb-artboard-command">{command}</pre> : null}
      </div>
      <button type="button" data-testid="bro-node-copy-command" className="ob-offline-banner-action" onClick={() => { void reveal(); }}>
        <span>{copied ? "Copied" : "Copy command"}</span>
        <SendHorizontal size={11} strokeWidth={2.2} />
      </button>
    </section>
  );
}

function ThreadPanel({
  bro,
  records,
  textTurns,
  audioTurns,
  conversationMessages,
  disabled,
  disabledReason,
}: {
  bro: BroCardModel;
  records: BroTaskRecord[];
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  conversationMessages: ChatMessage[];
  disabled?: boolean;
  disabledReason?: string | null;
}) {
  const shell = useNewbroShell();
  const draftText = shell.draftSession?.current_draft?.text ?? "";
  const timelineEntries = buildTimelineEntries({ records, textTurns, audioTurns, conversationMessages });

  return (
    <>
      <h1 className="sr-only">{bro.name}</h1>
      <span className="sr-only">Current draft</span>
      {disabled && disabledReason ? (
        <div className="dt-turn dt-turn-sys">
          <div className="dt-sys-event">
            <span className="dt-sys-event-dot" />
            <span>{disabledReason}</span>
          </div>
        </div>
      ) : null}
      {shell.openingThreadId ? (
        <div className="dt-turn dt-turn-sys">
          <div className="dt-sys-event">
            <span className="dt-sys-event-dot" />
            <span>Fetching thread history...</span>
          </div>
        </div>
      ) : null}
      {shell.threadOpenError ? (
        <div className="dt-turn dt-turn-sys">
          <div className="dt-sys-event">
            <span className="dt-sys-event-dot" />
            <span>{shell.threadOpenError}</span>
          </div>
        </div>
      ) : null}
      <div className="dt-thread-day"><span>Current session</span></div>
      {draftText ? (
        <div className="dt-turn dt-turn-you">
          <div className="dt-bubble dt-bubble-you">{draftText}</div>
          <div className="dt-bubble-meta">Draft · ready to send</div>
        </div>
      ) : null}
      {timelineEntries.map((entry) => {
        if (entry.kind === "text") return <TextTurnBubble key={entry.id} turn={entry.turn} />;
        if (entry.kind === "audio") return <AudioTurnBubble key={entry.id} bro={bro} turn={entry.turn} />;
        if (entry.kind === "conversation") {
          return <ConversationMessageBubble key={entry.id} bro={bro} message={entry.message} />;
        }
        return (
          <SyncedTaskRecordTurn
            key={entry.id}
            bro={bro}
            record={entry.record}
            textTurns={textTurns}
            audioTurns={audioTurns}
          />
        );
      })}
      {records.length === 0 && textTurns.length === 0 && audioTurns.length === 0 && conversationMessages.length === 0 ? (
        <div className="dt-turn dt-turn-bro">
          <div className="dt-bubble dt-bubble-bro">
            {disabled ? "I am paused until the node reconnects." : "No thread yet. Tell me what to build."}
          </div>
          <div className="dt-bubble-meta">{bro.name} · standby</div>
        </div>
      ) : null}
    </>
  );
}

function MobileThreadSurface({
  bro,
  records,
  selectedThreadId,
  createNewThread,
  textTurns,
  audioTurns,
  conversationMessages,
  onTextTurn,
  onAudioTurn,
  onRemoveAudioTurn,
  onThreadResolved,
  disabled,
  disabledReason,
}: {
  bro: BroCardModel;
  records: BroTaskRecord[];
  selectedThreadId: string | null;
  createNewThread: boolean;
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  conversationMessages: ChatMessage[];
  onTextTurn: (turn: TextTurn) => void;
  onAudioTurn: (turn: AudioTurn) => void;
  onRemoveAudioTurn: (turnId: string) => void;
  onThreadResolved: (threadId: string | null) => void;
  disabled?: boolean;
  disabledReason?: string | null;
}) {
  const shell = useNewbroShell();
  const [draft, setDraft] = useState("");
  const threadBodyRef = useRef<HTMLElement | null>(null);
  const draftText = draft;
  const connected = shell.voiceSession.phase === "connected";
  const loading = shell.voiceSession.phase === "loading";
  const [inputMode, setInputMode] = useState<"ptt" | "free">("ptt");
  const audioState = activeCodexAudioState(shell, bro);
  const textState = activeCodexTextState(shell, bro);
  const textDisabled = Boolean(disabled) || !textState.enabled;
  const micDisabled = Boolean(disabled) || !audioState.enabled;
  const recorder = usePushToTalkAudio({
    sessionId: shell.activeShellSessionId,
    broId: bro.id,
    targetThreadId: selectedThreadId,
    disabled: micDisabled,
    onTurn: onAudioTurn,
    onRemoveTurn: onRemoveAudioTurn,
    onError: shell.setShellError,
    onSent: shell.refreshShellSession,
  });

  function submitText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitDraftText();
  }

  async function submitDraftText() {
    const text = draft.trim();
    if (!text || textDisabled || !shell.activeShellSessionId) return;
    const turnId = `text-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const createdAt = new Date().toISOString();
    onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "sending", createdAt });
    setDraft("");
    try {
      const response = await submitExecutorTextInstruction(shell.activeShellSessionId, {
        targetPersonaId: bro.id,
        targetThreadId: selectedThreadId,
        createNewThread,
        text,
      });
      onThreadResolved(response.target_thread_id);
      onTextTurn({ id: turnId, broId: bro.id, threadId: response.target_thread_id ?? selectedThreadId, text, status: "sent", createdAt });
      await shell.refreshShellSession();
    } catch (error: unknown) {
      const message = describeError(error, "Text could not be sent.");
      onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "failed", createdAt, error: message });
      shell.setShellError(message);
    }
  }

  function toggleVoice() {
    if (!shell.activeShellSessionId || disabled) return;
    if (connected) {
      void shell.stopMobileVoiceSession();
    } else {
      void shell.startMobileVoiceSession(bro.id);
    }
  }

  const timelineEntries = buildTimelineEntries({ records, textTurns, audioTurns, conversationMessages });
  const threadScrollVersion = [
    selectedThreadId ?? "new",
    records.map((record) => `${record.taskId}:${record.status}:${record.timestamp ?? ""}:${record.summary ?? ""}`).join("|"),
    textTurns.map((turn) => `${turn.id}:${turn.status}`).join("|"),
    audioTurns.map((turn) => `${turn.id}:${turn.status}:${turn.transcript ?? ""}`).join("|"),
  ].join("::");

  useEffect(() => {
    const element = threadBodyRef.current;
    if (!element) return;
    requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight;
    });
  }, [threadScrollVersion]);

  return (
    <>
      <main ref={threadBodyRef} className="thr-thread nb-mobile-thread-body" aria-label={`${bro.name} thread`}>
        <h1 className="sr-only">{bro.name}</h1>
        <span className="sr-only">Current draft</span>
        <div className="thr-day"><span>Current session</span></div>
        {draftText ? (
          <div className={`thr-turn thr-turn-you${disabled ? " nb-mobile-turn-blocked" : ""}`}>
            <div className={`thr-bubble thr-bubble-you${disabled ? " ob-bubble-failed" : ""}`}>{draftText}</div>
            <div className={`thr-meta${disabled ? " ob-meta-failed" : ""}`}>
              {disabled ? (
                <>
                  <span className="ob-meta-failed-icon" aria-hidden="true">!</span>
                  <span>Not delivered · waiting for node</span>
                </>
              ) : "Draft · ready to send"}
            </div>
          </div>
        ) : null}
        {disabled && disabledReason ? (
          <div className="thr-turn thr-turn-sys">
            <div className="ob-sys-event">
              <span className="ob-sys-event-dot" />
              <span>{disabledReason}</span>
            </div>
          </div>
        ) : null}
        {shell.openingThreadId ? (
          <div className="thr-turn thr-turn-sys">
            <div className="ob-sys-event">
              <span className="ob-sys-event-dot" />
              <span>Fetching thread history...</span>
            </div>
          </div>
        ) : null}
        {shell.threadOpenError ? (
          <div className="thr-turn thr-turn-sys">
            <div className="ob-sys-event">
              <span className="ob-sys-event-dot" />
              <span>{shell.threadOpenError}</span>
            </div>
          </div>
        ) : null}
        {timelineEntries.map((entry) => {
          if (entry.kind === "text") return <TextTurnBubble key={entry.id} turn={entry.turn} mobile />;
          if (entry.kind === "audio") return <AudioTurnBubble key={entry.id} bro={bro} turn={entry.turn} mobile />;
          if (entry.kind === "conversation") {
            return <ConversationMessageBubble key={entry.id} bro={bro} message={entry.message} mobile />;
          }
          return (
            <SyncedTaskRecordTurn
              key={entry.id}
              bro={bro}
              record={entry.record}
              textTurns={textTurns}
              audioTurns={audioTurns}
              mobile
            />
          );
        })}
        {records.length === 0 && textTurns.length === 0 && audioTurns.length === 0 && conversationMessages.length === 0 ? (
          <div className="thr-turn thr-turn-bro">
            <div className="thr-bubble thr-bubble-bro">
              {disabled ? "I am paused until the node reconnects." : "No thread yet. Tell me what to build."}
            </div>
            <div className="thr-meta">{bro.name} · standby</div>
          </div>
        ) : null}
      </main>
      <form className={`thr-composer nb-mobile-thread-composer${disabled ? " ob-composer-disabled" : ""}`} onSubmit={submitText}>
        {!disabled ? (
          <div className="mob-mode mob-mode-light" role="tablist" aria-label="Input mode">
            <button
              type="button"
              role="tab"
              aria-selected={inputMode === "ptt"}
              className={`mob-mode-btn${inputMode === "ptt" ? " mob-mode-btn-on" : ""}`}
              onClick={() => setInputMode("ptt")}
              title="Tap to send"
            >
              <span className="mob-mode-icon"><MessageSquare size={15} strokeWidth={2} /></span>
              <span className="mob-mode-label">Tap to send</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={inputMode === "free"}
              className={`mob-mode-btn${inputMode === "free" ? " mob-mode-btn-on" : ""}`}
              onClick={() => setInputMode("free")}
              title="Always on"
            >
              <span className="mob-mode-icon"><Radio size={15} strokeWidth={2} /></span>
              <span className="mob-mode-label">Always on</span>
            </button>
          </div>
        ) : null}
        {disabled ? (
          <div className="ob-composer-lock">
            <span className="ob-composer-lock-icon" aria-hidden="true">
              <WifiOff size={13} strokeWidth={2} />
            </span>
            <span className="ob-composer-lock-text">{disabledReason ? `Sending paused while ${disabledReason}` : "Sending paused while the node is offline."}</span>
          </div>
        ) : null}
        <div className={`thr-composer-row${disabled ? " ob-composer-row-disabled" : ""}`} aria-disabled={disabled || undefined}>
          {inputMode === "free" && !disabled ? (
            <button type="button" className={`thr-free${connected ? "" : " thr-free-open"}`} aria-label={connected ? "Stop voice session" : `Wake up ${bro.name}`} disabled={loading} onClick={toggleVoice}>
              <span className="thr-free-led thr-free-led-active" />
              <span className="thr-free-label">{connected ? "Listening..." : "Always on · tap to talk"}</span>
              <span className="thr-free-waves" aria-hidden="true">{Array.from({ length: 16 }).map((_, index) => <i key={index} style={{ height: `${4 + (index % 5) * 2}px` }} />)}</span>
            </button>
          ) : (
            <>
              <div className={disabled ? "thr-ptt-idle ob-ptt-idle-disabled" : "thr-ptt-input"}>
                {disabled ? <span className="thr-ptt-idle-dot" aria-hidden="true" /> : null}
                <label className="sr-only" htmlFor={`message-${bro.id}`}>Message</label>
                <input
                  id={`message-${bro.id}`}
                  className={disabled ? "nb-mobile-thread-input" : "thr-ptt-input-field"}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && draft.trim()) {
                      event.preventDefault();
                      void submitDraftText();
                    }
                  }}
                  placeholder={disabled ? "Reconnect the node before sending" : textState.enabled ? `Message ${bro.name} - or hold the mic to talk` : textState.reason}
                  disabled={disabled}
                />
              </div>
              {draftText && !disabled ? (
                <button
                  type="submit"
                  className="thr-mic-btn thr-mic-btn-send"
                  aria-label={textDisabled ? textState.reason : "Send message"}
                  disabled={textDisabled}
                >
                  <ArrowUp size={22} strokeWidth={2.4} aria-hidden="true" />
                </button>
              ) : (
                <button
                  type="button"
                  data-testid="voice-session-start"
                  className={`thr-mic-btn thr-mic-btn-${micDisabled ? "idle ob-mic-disabled" : recorder.phase === "recording" ? "listening" : "idle"}`}
                  aria-label={micDisabled ? audioState.reason : `Hold to record for ${bro.name}`}
                  title={micDisabled ? audioState.reason : "Hold to record audio"}
                  disabled={micDisabled || loading || recorder.phase === "sending"}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    void recorder.start();
                  }}
                  onPointerUp={(event) => {
                    event.preventDefault();
                    void recorder.stopAndSend();
                  }}
                  onPointerCancel={recorder.cancel}
                  onBlur={recorder.cancel}
                  onKeyDown={(event) => {
                    if ((event.key === " " || event.key === "Enter") && recorder.phase === "idle") {
                      event.preventDefault();
                      void recorder.start();
                    }
                  }}
                  onKeyUp={(event) => {
                    if (event.key === " " || event.key === "Enter") {
                      event.preventDefault();
                      void recorder.stopAndSend();
                    }
                  }}
                >
                  <span className="thr-mic-halo" aria-hidden="true" />
                  <span className="thr-mic-halo thr-mic-halo-2" aria-hidden="true" />
                  <Mic size={22} strokeWidth={2} aria-hidden="true" />
                </button>
              )}
            </>
          )}
          {disabled ? <button type="submit" className="sr-only">Send message</button> : null}
        </div>
      </form>
    </>
  );
}

function DesktopComposerBar({
  bro,
  selectedThreadId,
  createNewThread,
  disabled,
  onTextTurn,
  onAudioTurn,
  onRemoveAudioTurn,
  onThreadResolved,
}: {
  bro: BroCardModel;
  selectedThreadId: string | null;
  createNewThread: boolean;
  disabled: boolean;
  onTextTurn: (turn: TextTurn) => void;
  onAudioTurn: (turn: AudioTurn) => void;
  onRemoveAudioTurn: (turnId: string) => void;
  onThreadResolved: (threadId: string | null) => void;
}) {
  const shell = useNewbroShell();
  const [draft, setDraft] = useState("");
  const connected = shell.voiceSession.phase === "connected";
  const loading = shell.voiceSession.phase === "loading";
  const audioState = activeCodexAudioState(shell, bro);
  const textState = activeCodexTextState(shell, bro);
  const textDisabled = disabled || !textState.enabled;
  const micDisabled = disabled || !audioState.enabled;
  const recorder = usePushToTalkAudio({
    sessionId: shell.activeShellSessionId,
    broId: bro.id,
    targetThreadId: selectedThreadId,
    disabled: micDisabled,
    onTurn: onAudioTurn,
    onRemoveTurn: onRemoveAudioTurn,
    onError: shell.setShellError,
    onSent: shell.refreshShellSession,
  });

  async function submitText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || textDisabled || !shell.activeShellSessionId) return;
    const turnId = `text-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const createdAt = new Date().toISOString();
    onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "sending", createdAt });
    setDraft("");
    try {
      const response = await submitExecutorTextInstruction(shell.activeShellSessionId, {
        targetPersonaId: bro.id,
        targetThreadId: selectedThreadId,
        createNewThread,
        text,
      });
      onThreadResolved(response.target_thread_id);
      onTextTurn({ id: turnId, broId: bro.id, threadId: response.target_thread_id ?? selectedThreadId, text, status: "sent", createdAt });
      await shell.refreshShellSession();
    } catch (error: unknown) {
      const message = describeError(error, "Text could not be sent.");
      onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "failed", createdAt, error: message });
      shell.setShellError(message);
    }
  }

  return (
    <form className={`dt-cmp${disabled ? " dt-cmp-disabled" : ""}`} onSubmit={submitText}>
      <div className="dt-cmp-head">
        <div className={`dt-cmp-modes${disabled ? " dt-cmp-modes-off" : ""}`} aria-label="Voice mode">
          <button type="button" className="dt-cmp-mode dt-cmp-mode-on">
            <span className={`dt-cmp-mode-dot dt-cmp-mode-dot-ptt${!connected && !disabled ? " dt-cmp-mode-dot-on" : ""}`} />
            Push to talk
          </button>
          <button type="button" className="dt-cmp-mode" disabled={disabled}>
            <span className={`dt-cmp-mode-dot dt-cmp-mode-dot-free${connected ? " dt-cmp-mode-dot-on" : ""}`} />
            Open channel
          </button>
        </div>
        <span className="dt-cmp-hint">
          <kbd className="dt-kbd">space</kbd>
          {disabled ? "node required before sending" : "type sends directly"}
        </span>
      </div>
      <div className="dt-cmp-bar">
        <label className="sr-only" htmlFor={`message-${bro.id}`}>Message</label>
        <input
          id={`message-${bro.id}`}
          className="dt-cmp-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={disabled ? "Reconnect the node before sending" : textState.enabled ? `Type to ${bro.name}...` : textState.reason}
          disabled={disabled}
        />
        <button
          type="button"
          data-testid="voice-session-start"
          className={`dt-cmp-mic dt-cmp-mic-${micDisabled ? "off" : recorder.phase === "recording" ? "free" : "ptt"}`}
          aria-label={micDisabled ? audioState.reason : "Hold to record audio"}
          title={micDisabled ? audioState.reason : "Hold to record audio"}
          disabled={micDisabled || loading || recorder.phase === "sending"}
          onPointerDown={(event) => {
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            void recorder.start();
          }}
          onPointerUp={(event) => {
            event.preventDefault();
            void recorder.stopAndSend();
          }}
          onPointerCancel={recorder.cancel}
          onBlur={recorder.cancel}
          onKeyDown={(event) => {
            if ((event.key === " " || event.key === "Enter") && recorder.phase === "idle") {
              event.preventDefault();
              void recorder.start();
            }
          }}
          onKeyUp={(event) => {
            if (event.key === " " || event.key === "Enter") {
              event.preventDefault();
              void recorder.stopAndSend();
            }
          }}
        >
          <Mic size={18} aria-hidden="true" />
        </button>
        <button
          type="submit"
          className="dt-cmp-send"
          aria-label={textDisabled ? textState.reason : "Send message"}
          disabled={textDisabled || !draft.trim()}
        >
          <SendHorizontal size={16} strokeWidth={2.2} />
        </button>
      </div>
    </form>
  );
}

function DesktopActivityRail({
  bro,
  threads,
  totalThreadCount,
  selectedThreadId,
  pendingNewThread,
  onSelectThread,
  onNewThread,
  onShowMore,
  offline,
}: {
  bro: BroCardModel;
  threads: BroThreadRecord[];
  totalThreadCount: number;
  selectedThreadId: string | null;
  pendingNewThread: boolean;
  onSelectThread: (threadId: string) => void;
  onNewThread: () => void;
  onShowMore: () => void;
  offline: ExecutorNodeRecord | null;
}) {
  const threadList = threads ?? [];
  const hiddenThreadCount = Math.max(0, totalThreadCount - threadList.length);
  return (
    <aside className="dt-activity nb-detail-activity" aria-label={`${bro.name} threads`}>
      <section className="dt-activity-block">
        <div className="dt-activity-block-head">
          <span className="ob-eyebrow">THREADS WITH {bro.name.toUpperCase()} · {totalThreadCount + (pendingNewThread ? 1 : 0)}</span>
        </div>
        <ul className="dt-threadlist">
          {pendingNewThread ? (
            <li>
              <button type="button" className="dt-threadlist-row dt-threadlist-row-on">
                <span className="dt-threadlist-body">
                  <span className="dt-threadlist-title">New thread</span>
                  <span className="dt-threadlist-meta">
                    <span>pending</span>
                    <span className="dt-bro-meta-sep">·</span>
                    <span>created on first send</span>
                  </span>
                </span>
                <span className="dt-threadlist-pip" />
              </button>
            </li>
          ) : null}
          {threadList.map((thread) => (
            <li key={thread.threadId}>
              <button
                type="button"
                className={`dt-threadlist-row${!pendingNewThread && selectedThreadId === thread.threadId ? " dt-threadlist-row-on" : ""}`}
                onClick={() => onSelectThread(thread.threadId)}
              >
                <span className="dt-threadlist-body">
                  <span className="dt-threadlist-title">{thread.title}</span>
                  <span className="dt-threadlist-meta">
                    <span>{thread.timeLabel || thread.statusLabel}</span>
                  </span>
                </span>
                <span className={`dt-threadlist-pip${offline ? " dt-threadlist-pip-paused" : ""}`} />
              </button>
            </li>
          ))}
        </ul>
        {hiddenThreadCount > 0 ? (
          <button type="button" className="dt-thread-more" onClick={onShowMore}>
            <Layers size={12} strokeWidth={2.2} aria-hidden="true" />
            <span>Show {Math.min(THREAD_LIST_PAGE_SIZE, hiddenThreadCount)} more</span>
          </button>
        ) : null}
        <button type="button" className="dt-thread-new" onClick={onNewThread}>
          <Plus size={12} strokeWidth={2.4} aria-hidden="true" />
          <span>New thread with {bro.name}</span>
        </button>
      </section>
    </aside>
  );
}

function DesktopVoiceDock({
  phase,
  disabled,
  onToggle,
}: {
  phase: ReturnType<typeof useNewbroShell>["voiceSession"]["phase"];
  disabled: boolean;
  onToggle: () => void;
}) {
  const connected = phase === "connected";
  return (
    <div className="nb-talk-dock">
      <div className="nb-talk-hint"><span className="nb-talk-key">space</span><span>{connected ? "voice channel open" : "push to talk anywhere"}</span></div>
      <button
        type="button"
        className={`nb-talk-btn${connected ? " nb-talk-btn-listening" : ""}`}
        data-testid={connected ? "voice-session-stop" : "voice-session-start"}
        aria-label={connected ? "Stop voice session" : "Start voice session"}
        disabled={disabled || phase === "loading"}
        onClick={onToggle}
      >
        <Mic size={18} aria-hidden="true" />
        <span>{connected ? "Stop voice" : "Start voice"}</span>
      </button>
    </div>
  );
}

function DesktopDetail({ broId, onHome }: { broId: string; onHome: () => void }) {
  const shell = useNewbroShell();
  const [textTurns, setTextTurns] = useState<TextTurn[]>([]);
  const [audioTurns, setAudioTurns] = useState<AudioTurn[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => readThreadIdFromUrl());
  const [pendingNewThread, setPendingNewThread] = useState(false);
  const [threadVisibleCount, setThreadVisibleCount] = useState(THREAD_LIST_PAGE_SIZE);
  const openedThreadRef = useRef<string | null>(null);
  const activeThreadRef = useRef<string | null>(null);
  const threadScrollRef = useRef<HTMLDivElement | null>(null);
  const bro = shell.bros.find((candidate) => candidate.id === broId) ?? null;
  const nodeState = deriveBroNodeState(bro, shell.executorNodes);
  const needsConnect = bro?.source === "runtime" && nodeStateNeedsConnect(nodeState);
  const offline = nodeState.kind === "usable_disconnected" ? nodeState.node : null;
  const persona = bro?.source === "runtime" ? shell.runtimePersonas.find((item) => item.persona_id === bro.id) ?? null : null;
  const threads = bro?.source === "runtime" ? buildBroThreadRecords(bro.id, shell.broThreads) : [];
  const selectedThread = !pendingNewThread
    ? threads.find((thread) => thread.threadId === selectedThreadId) ?? threads[0] ?? null
    : null;
  const activeThreadId = pendingNewThread ? null : selectedThread?.threadId ?? null;
  const visibleThreads = useMemo(
    () => threads.slice(0, threadVisibleCount),
    [threadVisibleCount, threads],
  );
  const records = bro?.source === "runtime"
    ? buildBroTaskRecords(bro.id, {
        activeTaskId: persona?.current_task_id ?? null,
        broDetailSessionId: persona?.bro_detail_session_id ?? null,
        tasks: shell.tasks,
        executionRuns: shell.executionRuns,
        summaries: shell.taskSummaries,
        taskIds: selectedThread?.taskIds ?? null,
        limit: 20,
      })
    : [];
  const threadScrollVersion = [
    activeThreadId ?? "new",
    records.map((record) => `${record.taskId}:${record.status}:${record.timestamp ?? ""}:${record.summary ?? ""}`).join("|"),
    textTurns.filter((turn) => turn.broId === broId && turnMatchesThread(turn, activeThreadId)).map((turn) => `${turn.id}:${turn.status}`).join("|"),
    audioTurns.filter((turn) => turn.broId === broId && turnMatchesThread(turn, activeThreadId)).map((turn) => `${turn.id}:${turn.status}:${turn.transcript ?? ""}`).join("|"),
  ].join("::");

  useEffect(() => {
    if (pendingNewThread || threads.length === 0) return;
    const exists = selectedThreadId ? threads.some((thread) => thread.threadId === selectedThreadId) : false;
    if (!exists) {
      setSelectedThreadId(threads[0].threadId);
      replaceThreadIdInUrl(threads[0].threadId);
    }
  }, [pendingNewThread, selectedThreadId, threads]);

  useEffect(() => {
    setThreadVisibleCount(THREAD_LIST_PAGE_SIZE);
  }, [broId]);

  useEffect(() => {
    if (!activeThreadId) return;
    const selectedIndex = threads.findIndex((thread) => thread.threadId === activeThreadId);
    if (selectedIndex < threadVisibleCount) return;
    setThreadVisibleCount(Math.ceil((selectedIndex + 1) / THREAD_LIST_PAGE_SIZE) * THREAD_LIST_PAGE_SIZE);
  }, [activeThreadId, threadVisibleCount, threads]);

  function selectThread(threadId: string) {
    setPendingNewThread(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
  }

  function newThread() {
    if (bro?.source === "runtime") {
      void shell.closeRuntimeBroThread(bro.id, activeThreadId);
    }
    setPendingNewThread(true);
    setSelectedThreadId(null);
    replaceThreadIdInUrl(null);
  }

  function resolveThread(threadId: string | null) {
    if (!threadId) return;
    setPendingNewThread(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
  }

  useEffect(() => {
    if (pendingNewThread || needsConnect || !bro || bro.source !== "runtime" || !activeThreadId) return;
    if (openedThreadRef.current === activeThreadId) return;
    openedThreadRef.current = activeThreadId;
    void shell.openRuntimeBroThread(bro.id, activeThreadId);
  }, [activeThreadId, bro?.id, bro?.source, needsConnect, pendingNewThread]);

  useEffect(() => {
    activeThreadRef.current = activeThreadId;
  }, [activeThreadId]);

  useEffect(() => {
    return () => {
      if (bro?.source === "runtime") {
        void shell.closeRuntimeBroThread(bro.id, activeThreadRef.current);
      }
    };
  }, [bro?.id, bro?.source]);

  useEffect(() => {
    const element = threadScrollRef.current;
    if (!element) return;
    requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight;
    });
  }, [threadScrollVersion]);

  useEffect(() => {
    if (!shell.hasLoadedShellSnapshot || !shell.activeShellSessionId || !bro || needsConnect) return undefined;
    const sessionId = shell.activeShellSessionId;
    void setVoiceTarget(sessionId, bro.id);
    return () => { void clearVoiceTarget(sessionId).catch(() => undefined); };
  }, [shell.hasLoadedShellSnapshot, shell.activeShellSessionId, bro?.id, needsConnect]);

  useEffect(() => {
    setAudioTurns((current) => applyAudioTranscripts(current, shell.executionRuns));
  }, [shell.executionRuns]);

  if (!shell.hasLoadedShellSnapshot) return null;
  if (!bro) return <DesktopHome onOpenBro={() => undefined} />;

  const disabledReason = offline ? `${offline.name} is not connected.` : null;
  const visibleTextTurns = textTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleAudioTurns = audioTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleConversationMessages = shell.chatMessages.slice(-8);
  const upsertTextTurn = (turn: TextTurn) => {
    setTextTurns((current) => {
      const existing = current.findIndex((candidate) => candidate.id === turn.id);
      if (existing === -1) return [...current, turn];
      const next = [...current];
      next[existing] = turn;
      return next;
    });
  };
  const upsertAudioTurn = (turn: AudioTurn) => {
    setAudioTurns((current) => {
      const existing = current.findIndex((candidate) => candidate.id === turn.id);
      if (existing === -1) return [...current, turn];
      const next = [...current];
      next[existing] = turn;
      return next;
    });
  };
  const removeAudioTurn = (turnId: string) => {
    setAudioTurns((current) => current.filter((turn) => turn.id !== turnId));
  };

  return (
    <DesktopFrame active="detail" bro={bro} onHome={onHome}>
      {needsConnect && shell.activeShellSessionId ? (
        <div className="dt-main-pad nb-detail-connect-stage">
          <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onHome} onCreated={shell.refreshShellSession} bro={bro} />
        </div>
      ) : null}
      {!needsConnect ? (
        <div className="dt-detail-v2 nb-detail-runtime">
          <DesktopActivityRail
            bro={bro}
            threads={visibleThreads}
            totalThreadCount={threads.length}
            selectedThreadId={activeThreadId}
            pendingNewThread={pendingNewThread}
            onSelectThread={selectThread}
            onNewThread={newThread}
            onShowMore={() => setThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE)}
            offline={offline}
          />
          <section className="dt-pane">
            <div className="dt-pane-scroll" ref={threadScrollRef}>
              <div className="dt-pane-content">
                {offline ? <OfflineBanner bro={bro} node={offline} sessionId={shell.activeShellSessionId} /> : null}
                <ThreadPanel
                  bro={bro}
                  records={records}
                  textTurns={visibleTextTurns}
                  audioTurns={visibleAudioTurns}
                  conversationMessages={visibleConversationMessages}
                  disabled={Boolean(offline)}
                  disabledReason={disabledReason}
                />
              </div>
            </div>
            <DesktopComposerBar
              bro={bro}
              selectedThreadId={activeThreadId}
              createNewThread={pendingNewThread}
              disabled={Boolean(offline)}
              onTextTurn={upsertTextTurn}
              onAudioTurn={upsertAudioTurn}
              onRemoveAudioTurn={removeAudioTurn}
              onThreadResolved={resolveThread}
            />
          </section>
        </div>
      ) : null}
    </DesktopFrame>
  );
}

function MobileBroCard({ bro, onOpen }: { bro: BroCardModel; onOpen: (id: string) => void }) {
  const state = homeBroState(bro);
  const tone = homeBroTone(state);
  return (
    <button type="button" data-testid={`mobile-bro-row-${bro.id}`} className={state === "working" ? "home-card" : "home-row"} onClick={() => onOpen(bro.id)}>
      <div className={state === "working" ? `home-card-avatar home-card-avatar-${tone}` : `home-row-avatar home-row-avatar-${state}`}>
        <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={state === "working" ? 36 : 25} />
      </div>
      <div className={state === "working" ? "home-card-headtext" : "home-row-body"}>
        <div className={state === "working" ? "home-card-name" : "home-row-name"}>{bro.name}</div>
        <div className={state === "working" ? "home-card-role" : "home-row-task"}>{state === "working" ? bro.taskTitle : homeBroLast(bro, state)}</div>
      </div>
      <span className={`home-chip home-chip-${tone}`}><span className="home-chip-dot" />{homeBroChipLabel(state)}</span>
    </button>
  );
}

function MobileStage({ children }: { children: React.ReactNode }) {
  return (
    <div className="nb-mobile-stage" data-testid="mobile-walkie">
      <div className="nb-mobile-phone">
        <div className="nb-mobile-status"><span>9:41</span><span className="nb-mobile-battery" aria-hidden="true"><span /></span></div>
        {children}
      </div>
    </div>
  );
}

function MobileHome({ onOpenBro }: { onOpenBro: (id: string) => void }) {
  const shell = useNewbroShell();
  const [sheetOpen, setSheetOpen] = useState(false);
  const homeBros = useMemo(() => [...shell.bros].sort(compareHomeBros), [shell.bros]);
  const working = homeBros.filter((bro) => homeBroState(bro) === "working");
  const standing = homeBros.filter((bro) => homeBroState(bro) !== "working");
  const recents = buildHomeRecents(shell.tasks, shell.runtimePersonas);
  if (!shell.hasLoadedShellSnapshot) return null;
  return (
    <MobileStage>
      <div className={`home nb-mobile-home${shell.runtimePersonas.length === 0 ? " ob-firsthome" : ""}`} data-testid="mobile-home">
        <header className="home-bar">
          <div className="home-bar-l">
            <div className="home-bar-logo"><img src="/newbro.webp" alt="" draggable={false} /></div>
            <div className="home-bar-titles">
              <div className="home-bar-greet">Hi · workspace</div>
              <div className="home-bar-meta">{shell.runtimePersonas.length === 0 ? "workspace is empty · let's fix that" : `${working.length} of ${shell.bros.length} bros working · ${recents.length} sessions`}</div>
            </div>
          </div>
          <button type="button" className="home-bar-btn" aria-label="Settings">
            <Settings size={19} strokeWidth={1.9} />
          </button>
        </header>
        <main className={shell.runtimePersonas.length === 0 ? "ob-firsthome-body" : "home-body"}>
          {shell.runtimePersonas.length === 0 ? (
            <>
            <section className="ob-hero-card" data-testid="mobile-empty-workspace">
              <div className="ob-hero-art">
                <div className="ob-hero-art-bg" aria-hidden="true">{Array.from({ length: 28 }).map((_, index) => <i key={index} style={{ animationDelay: `${(index % 7) * 0.15}s` }} />)}</div>
                <div className="ob-hero-mascot"><img src="/newbro.webp" alt="" draggable={false} /></div>
                <span className="ob-hero-zzz" aria-hidden="true"><i>z</i><i>z</i><i>z</i></span>
              </div>
              <div className="ob-hero-body">
                <span className="ob-eyebrow ob-eyebrow-coral">YOUR CREW · 0 BROS</span>
                <h2 className="ob-hero-h">You don't have a bro yet.</h2>
                <p className="ob-hero-sub">Create a worker persona, bind it to a user-owned executor node, and it will appear here after Newbro can use it.</p>
                <div className="ob-hero-actions">
                  <button type="button" className="ob-cta ob-cta-block" onClick={() => setSheetOpen(true)}>
                    <Plus size={15} strokeWidth={2.4} />
                    <span>Create your first bro</span>
                  </button>
                </div>
              </div>
            </section>
            <section className="ob-ghost-section">
              <div className="ob-explain-head"><span className="ob-eyebrow">STANDING BY · 0</span></div>
              <div className="ob-ghost-list">
                <div className="ob-ghost-row"><span className="ob-ghost-avatar" /><span className="ob-ghost-lines"><span className="ob-ghost-line ob-ghost-line-lg" /><span className="ob-ghost-line ob-ghost-line-sm" /></span><span className="ob-ghost-chip" /></div>
                <div className="ob-ghost-row"><span className="ob-ghost-avatar" /><span className="ob-ghost-lines"><span className="ob-ghost-line ob-ghost-line-md" /><span className="ob-ghost-line ob-ghost-line-sm" /></span><span className="ob-ghost-chip" /></div>
              </div>
              <div className="ob-ghost-foot">These seats fill up after you connect a bro.</div>
            </section>
            </>
          ) : (
            <>
              {working.length > 0 ? (
                <section className="home-section">
                  <div className="home-section-head"><span className="home-section-eyebrow">In flight · {working.length}</span><span className="home-section-sub">Sessions currently dispatched</span></div>
                  <div className="home-flight">{working.map((bro) => <MobileBroCard key={bro.id} bro={bro} onOpen={onOpenBro} />)}</div>
                </section>
              ) : null}
              <section className="home-section">
                <div className="home-section-head"><span className="home-section-eyebrow">Standing by · {standing.length}</span></div>
                <div className="home-list">{standing.map((bro) => <MobileBroCard key={bro.id} bro={bro} onOpen={onOpenBro} />)}</div>
              </section>
            </>
          )}
          {recents.length > 0 ? (
            <section className="home-section">
              <div className="home-section-head"><span className="home-section-eyebrow">Recent · {recents.length}</span></div>
              <ul className="home-recents">{recents.map((recent) => <li key={recent.id}><div className="home-recent"><span className="home-recent-icon"><FileText size={13} /></span><span className="home-recent-body"><span className="home-recent-title">{recent.title}</span><span className="home-recent-meta">{recent.bro} · {recent.when}</span></span></div></li>)}</ul>
            </section>
          ) : null}
        </main>
        {shell.runtimePersonas.length > 0 ? (
          <div className="mobile-action-dock">
            <button
              type="button"
              className="home-fab"
              aria-label={shell.voiceSession.phase === "connected" ? "Stop voice session" : "Call NewBro"}
              onClick={() => {
                if (shell.voiceSession.phase === "connected") {
                  void shell.stopMobileVoiceSession();
                } else {
                  void shell.startMobileVoiceSession(null);
                }
              }}
            >
              {shell.voiceSession.phase === "connected" ? "Stop voice session" : "Call NewBro"}
            </button>
          </div>
        ) : null}
      </div>
      {sheetOpen && shell.activeShellSessionId ? <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSheetOpen(false)} onCreated={shell.refreshShellSession} /> : null}
    </MobileStage>
  );
}

function MobileDetail({ bro, onBack }: { bro: BroCardModel; onBack: () => void }) {
  const shell = useNewbroShell();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [textTurns, setTextTurns] = useState<TextTurn[]>([]);
  const [audioTurns, setAudioTurns] = useState<AudioTurn[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => readThreadIdFromUrl());
  const [pendingNewThread, setPendingNewThread] = useState(false);
  const [drawerThreadVisibleCount, setDrawerThreadVisibleCount] = useState(THREAD_LIST_PAGE_SIZE);
  const openedThreadRef = useRef<string | null>(null);
  const activeThreadRef = useRef<string | null>(null);
  const nodeState = deriveBroNodeState(bro, shell.executorNodes);
  const offline = nodeState.kind === "usable_disconnected" ? nodeState.node : null;
  const needsConnect = bro.source === "runtime" && nodeStateNeedsConnect(nodeState) && nodeState.kind !== "no_bound_node";
  const persona = bro.source === "runtime" ? shell.runtimePersonas.find((item) => item.persona_id === bro.id) ?? null : null;
  const threads = bro.source === "runtime" ? buildBroThreadRecords(bro.id, shell.broThreads) : [];
  const selectedThread = !pendingNewThread
    ? threads.find((thread) => thread.threadId === selectedThreadId) ?? threads[0] ?? null
    : null;
  const activeThreadId = pendingNewThread ? null : selectedThread?.threadId ?? null;
  const visibleDrawerThreads = useMemo(
    () => threads.slice(0, drawerThreadVisibleCount),
    [drawerThreadVisibleCount, threads],
  );
  const hiddenDrawerThreadCount = Math.max(0, threads.length - visibleDrawerThreads.length);
  const records = bro.source === "runtime"
    ? buildBroTaskRecords(bro.id, {
        activeTaskId: persona?.current_task_id ?? null,
        broDetailSessionId: persona?.bro_detail_session_id ?? null,
        tasks: shell.tasks,
        executionRuns: shell.executionRuns,
        summaries: shell.taskSummaries,
        taskIds: selectedThread?.taskIds ?? null,
        limit: 20,
    })
    : [];
  const visibleTextTurns = textTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleAudioTurns = audioTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleConversationMessages = shell.chatMessages.slice(-8);
  useEffect(() => {
    setAudioTurns((current) => applyAudioTranscripts(current, shell.executionRuns));
  }, [shell.executionRuns]);
  useEffect(() => {
    if (pendingNewThread || threads.length === 0) return;
    const exists = selectedThreadId ? threads.some((thread) => thread.threadId === selectedThreadId) : false;
    if (!exists) {
      setSelectedThreadId(threads[0].threadId);
      replaceThreadIdInUrl(threads[0].threadId);
    }
  }, [pendingNewThread, selectedThreadId, threads]);
  useEffect(() => {
    setDrawerThreadVisibleCount(THREAD_LIST_PAGE_SIZE);
  }, [bro.id]);
  useEffect(() => {
    if (!activeThreadId) return;
    const selectedIndex = threads.findIndex((thread) => thread.threadId === activeThreadId);
    if (selectedIndex < drawerThreadVisibleCount) return;
    setDrawerThreadVisibleCount(Math.ceil((selectedIndex + 1) / THREAD_LIST_PAGE_SIZE) * THREAD_LIST_PAGE_SIZE);
  }, [activeThreadId, drawerThreadVisibleCount, threads]);
  function selectThread(threadId: string) {
    setPendingNewThread(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
    setPickerOpen(false);
  }
  function newThread() {
    if (bro.source === "runtime") {
      void shell.closeRuntimeBroThread(bro.id, activeThreadId);
    }
    setPendingNewThread(true);
    setSelectedThreadId(null);
    replaceThreadIdInUrl(null);
    setPickerOpen(false);
  }
  function resolveThread(threadId: string | null) {
    if (!threadId) return;
    setPendingNewThread(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
  }
  useEffect(() => {
    if (pendingNewThread || needsConnect || bro.source !== "runtime" || !activeThreadId) return;
    if (openedThreadRef.current === activeThreadId) return;
    openedThreadRef.current = activeThreadId;
    void shell.openRuntimeBroThread(bro.id, activeThreadId);
  }, [activeThreadId, bro.id, bro.source, needsConnect, pendingNewThread]);
  useEffect(() => {
    activeThreadRef.current = activeThreadId;
  }, [activeThreadId]);
  useEffect(() => {
    return () => {
      if (bro.source === "runtime") {
        void shell.closeRuntimeBroThread(bro.id, activeThreadRef.current);
      }
    };
  }, [bro.id, bro.source]);
  const upsertAudioTurn = (turn: AudioTurn) => {
    setAudioTurns((current) => {
      const existing = current.findIndex((candidate) => candidate.id === turn.id);
      if (existing === -1) return [...current, turn];
      const next = [...current];
      next[existing] = turn;
      return next;
    });
  };
  const upsertTextTurn = (turn: TextTurn) => {
    setTextTurns((current) => {
      const existing = current.findIndex((candidate) => candidate.id === turn.id);
      if (existing === -1) return [...current, turn];
      const next = [...current];
      next[existing] = turn;
      return next;
    });
  };
  const removeAudioTurn = (turnId: string) => {
    setAudioTurns((current) => current.filter((turn) => turn.id !== turnId));
  };
  if (needsConnect && shell.activeShellSessionId) {
    return (
      <MobileStage>
        <div className="home nb-mobile-home">
          <header className="home-bar"><button type="button" className="home-section-link" onClick={onBack}>Home</button></header>
          <main className="home-body">
            <section className="nb-mobile-first-run">
              <span className="home-section-eyebrow">Connect · {bro.name}</span>
              <h2>Set up this Bro before talking.</h2>
              <p>Create or reveal a local executor command and run it on the machine where this Bro should work.</p>
              <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onBack} onCreated={shell.refreshShellSession} bro={bro} />
            </section>
          </main>
        </div>
      </MobileStage>
    );
  }
  return (
    <MobileStage>
      <div className={`thr nb-mobile-runtime-thread nb-mobile-detail-content${offline ? " nb-mobile-runtime-thread-offline ob-thr-offline" : ""}`} data-testid={`mobile-bro-focus-${bro.id}`}>
        <header className="thr-bar">
          <button type="button" className="thr-back" aria-label="Back" onClick={onBack}>
            <ChevronLeft size={20} strokeWidth={2.2} />
          </button>
          <div className="thr-bar-bro">
            <div className={`thr-bar-avatar${offline ? " ob-avatar-offline" : ""}`}>
              <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={offline ? "offline" : "working"} size={30} />
              {offline ? <span className="ob-avatar-offline-pip" aria-hidden="true" /> : null}
            </div>
            <div className="thr-bar-meta">
              <div className="thr-bar-title-row">
                <span className="thr-bar-name">{bro.name}</span>
                <span className="thr-bar-sep">·</span>
                <span className="thr-bar-thread-title">{bro.taskTitle || "Current draft"}</span>
              </div>
              <div className={`thr-bar-state thr-bar-state-${offline ? "warn" : "live"}`}>
                <span className="thr-bar-dot" />
                {offline ? `Offline · ${offline.name}` : "Live · ready"}
              </div>
            </div>
          </div>
          <button type="button" className="thr-more" aria-label="Switch thread" onClick={() => setPickerOpen(true)}>
            <Layers size={20} strokeWidth={1.9} />
          </button>
        </header>
        {pickerOpen ? <div className="thr-drawer-backdrop" onClick={() => setPickerOpen(false)} /> : null}
        <aside className={`thr-drawer${pickerOpen ? " thr-drawer-open" : ""}`} aria-hidden={!pickerOpen}>
          <header className="thr-drawer-head">
            <div>
              <div className="thr-drawer-eyebrow">Threads with</div>
              <div className="thr-drawer-title">{bro.name}</div>
            </div>
            <button type="button" className="thr-drawer-close" onClick={() => setPickerOpen(false)} aria-label="Close">
              <X size={18} strokeWidth={2} />
            </button>
          </header>
          <ul className="thr-drawer-list">
            {pendingNewThread ? (
              <li>
                <button type="button" className="thr-drawer-item thr-drawer-item-open thr-drawer-item-on" onClick={() => setPickerOpen(false)}>
                  <span className="thr-drawer-item-dot" aria-hidden="true" />
                  <span className="thr-drawer-item-body">
                    <span className="thr-drawer-item-title">New thread</span>
                    <span className="thr-drawer-item-meta">
                      <span className="thr-drawer-item-state">pending</span>
                      <span className="thr-drawer-item-sep">·</span>
                      <span className="thr-drawer-item-when">first send</span>
                    </span>
                  </span>
                  <span className="thr-drawer-item-check" aria-hidden="true">
                    <Check size={14} strokeWidth={2.2} />
                  </span>
                </button>
              </li>
            ) : null}
            {visibleDrawerThreads.map((thread) => (
              <li key={thread.threadId}>
                <button
                  type="button"
                  className={`thr-drawer-item ${thread.status === "running" ? "thr-drawer-item-working" : "thr-drawer-item-open"}${!pendingNewThread && activeThreadId === thread.threadId ? " thr-drawer-item-on" : ""}`}
                  onClick={() => selectThread(thread.threadId)}
                >
                <span className="thr-drawer-item-dot" aria-hidden="true" />
                <span className="thr-drawer-item-body">
                  <span className="thr-drawer-item-title">{thread.title}</span>
                  <span className="thr-drawer-item-meta">
                    <span className="thr-drawer-item-state">{thread.statusLabel}</span>
                    {thread.timeLabel ? (
                      <>
                        <span className="thr-drawer-item-sep">·</span>
                        <span className="thr-drawer-item-when">{thread.timeLabel}</span>
                      </>
                    ) : null}
                  </span>
                </span>
                {!pendingNewThread && activeThreadId === thread.threadId ? (
                  <span className="thr-drawer-item-check" aria-hidden="true">
                    <Check size={14} strokeWidth={2.2} />
                  </span>
                ) : null}
                </button>
              </li>
            ))}
          </ul>
          {hiddenDrawerThreadCount > 0 ? (
            <button
              type="button"
              className="thr-drawer-more"
              onClick={() => setDrawerThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE)}
            >
              <Layers size={14} strokeWidth={2.2} />
              <span>Show {Math.min(THREAD_LIST_PAGE_SIZE, hiddenDrawerThreadCount)} more</span>
            </button>
          ) : null}
          <button type="button" className="thr-drawer-new" onClick={newThread}>
            <Plus size={14} strokeWidth={2.2} />
            <span>New thread with {bro.name}</span>
          </button>
        </aside>
        {offline ? <OfflineBanner bro={bro} node={offline} sessionId={shell.activeShellSessionId} /> : null}
        <MobileThreadSurface
          bro={bro}
          records={records}
          selectedThreadId={activeThreadId}
          createNewThread={pendingNewThread}
          textTurns={visibleTextTurns}
          audioTurns={visibleAudioTurns}
          conversationMessages={visibleConversationMessages}
          onTextTurn={upsertTextTurn}
          onAudioTurn={upsertAudioTurn}
          onRemoveAudioTurn={removeAudioTurn}
          onThreadResolved={resolveThread}
          disabled={Boolean(offline)}
          disabledReason={offline ? `${offline.name} is not connected.` : null}
        />
      </div>
    </MobileStage>
  );
}

export function ArtboardHomePage({ onOpenBro }: { onOpenBro: (broId: string) => void }) {
  return <DesktopHome onOpenBro={onOpenBro} />;
}

export function ArtboardBroDetailPage({ broId, onHome }: { broId: string; onHome: () => void }) {
  return <DesktopDetail broId={broId} onHome={onHome} />;
}

export function ArtboardMobilePage() {
  const shell = useNewbroShell();
  const [detailId, setDetailId] = useState<string | null>(null);
  const detailBro = detailId ? shell.bros.find((bro) => bro.id === detailId) ?? null : null;
  if (detailBro) return <MobileDetail bro={detailBro} onBack={() => setDetailId(null)} />;
  return <MobileHome onOpenBro={setDetailId} />;
}

export function buildRuntimeBroCards(
  personas: Persona[],
  nodes: ExecutorNodeRecord[],
  shell: Pick<ReturnType<typeof useNewbroShell>, "executionRuns" | "taskSummaries" | "tasks">,
) {
  return buildBroCardModels(personas, nodes, shell.executionRuns, shell.taskSummaries, shell.tasks);
}
