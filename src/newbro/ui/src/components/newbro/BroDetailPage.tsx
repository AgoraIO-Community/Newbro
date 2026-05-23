import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import {
  heartbeatSttSession,
  leaveSttSession,
  prepareSttSession,
  startSttSession,
  type SttSessionPrepareResponse,
  type SttSessionStartResponse,
} from "../../lib/connector-client";
import { clearDraft, sendDraft, submitDraftAsrTurn, submitTaskCommand } from "../../lib/session-client";
import { loadAgoraBrowserStack } from "../../lib/voice-runtime";
import { describeProtobufTranscriptPayload, describeTranscriptPayload, extractTranscriptText, type ExtractedSttTranscript } from "./stt-transcript";
import { BroDetailHeader, DraftBrainPanel, LiveTranscriptPanel, RunnerBrainPanel, VoicePad } from "./visual";
import type { BroCardModel, BroTaskRecord } from "./types";
import type { AgentEvent, DraftOutputCompletedStreamEvent, DraftOutputDeltaStreamEvent, DraftOutputFailedStreamEvent, DraftOutputStartedStreamEvent, TaskSummary } from "../../types";

const HEARTBEAT_INTERVAL_MS = 15_000;
const STT_SILENCE_COMMIT_MS = 1_200;
const STT_RELEASE_AUDIO_TAIL_MS = 500;
type MicCaptureState = "muted" | "held" | "tail";
type Draft = {
  text: string;
  last_update_summary?: string;
};

type DraftSession = {
  id: string;
  current_draft: Draft | null;
  current_dispatch_plan?: {
    plan_id: string;
    target_agent: string;
    mode: string;
    task_title: string;
    task_goal: string;
    missing_context: string[];
    output_language: string;
  } | null;
  status: string;
};

type DraftOutputEvent =
  | DraftOutputStartedStreamEvent
  | DraftOutputDeltaStreamEvent
  | DraftOutputCompletedStreamEvent
  | DraftOutputFailedStreamEvent;

type MobileDetailPage = "draft" | "status";

function normalizeTranscriptSegmentForDisplay(text: string) {
  return text.replace(/\s*\n+\s*/g, " ").trim();
}

function hasCjkBoundary(current: string, next: string) {
  return /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]$/u.test(current)
    && /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(next);
}

function appendTranscriptSegment(current: string, next: string) {
  const segment = normalizeTranscriptSegmentForDisplay(next);
  if (!segment) return current;
  if (!current) return segment;
  if (
    /[,.;:!?，。！？、；：）】》」』]$/.test(current)
    || /^[,.;:!?，。！？、；：）】》」』]/.test(segment)
    || hasCjkBoundary(current, segment)
  ) {
    return `${current}${segment}`;
  }
  return `${current} ${segment}`;
}

function composeTranscriptText(segments: string[]) {
  return segments.reduce((current, segment) => appendTranscriptSegment(current, segment), "");
}

type SentenceSegment = {
  uid: string;
  startTime: number;
  text: string;
  textTs: number;
  revision: number;
  arrivalIndex: number;
  pendingFinal?: {
    text: string;
    textTs: number;
    revision: number;
    arrivalIndex: number;
  };
};

type SentenceUpdateResult = {
  text: string;
  action: "create-sentence" | "replace-sentence" | "hold-final-fragment" | "replace-sentence-with-held-final" | "drop-missing-time-metadata" | "drop-stale-sentence";
  segments: Map<string, SentenceSegment>;
  sentenceKey?: string;
  sentenceStartTime?: number;
  existingTextTs?: number;
  textTs?: number;
  pendingFinalTextTs?: number;
  pendingFinalLength?: number;
  heldFinalApplied?: boolean;
  sentencesCount: number;
  reason?: string;
};

function transcriptUid(candidate: ExtractedSttTranscript) {
  return candidate.uid == null ? "default" : String(candidate.uid);
}

function sentenceKey(candidate: ExtractedSttTranscript) {
  if (candidate.time == null || candidate.time <= 0) return null;
  return `${transcriptUid(candidate)}:${candidate.time}`;
}

function provisionalSentenceKey(candidate: ExtractedSttTranscript) {
  return `${transcriptUid(candidate)}:provisional`;
}

function transcriptEndTime(candidate: ExtractedSttTranscript) {
  if (candidate.textTs != null) return candidate.textTs;
  if (candidate.time != null && candidate.durationMs != null) return candidate.time + candidate.durationMs;
  return candidate.time;
}

function transcriptRevision(candidate: ExtractedSttTranscript, arrivalIndex: number) {
  return candidate.seqnum
    ?? candidate.offtime
    ?? candidate.durationMs
    ?? transcriptEndTime(candidate)
    ?? arrivalIndex;
}

function rebuildSentenceTranscript(segments: Map<string, SentenceSegment>) {
  return composeTranscriptText([...segments.values()].sort((left, right) => {
    if (left.startTime !== right.startTime) return left.startTime - right.startTime;
    return left.arrivalIndex - right.arrivalIndex;
  }).map((segment) => segment.text).filter(Boolean));
}

function serializeTranscriptSegmentsForDebug(segments: Map<string, SentenceSegment>) {
  return [...segments.entries()]
    .sort(([, left], [, right]) => {
      if (left.startTime !== right.startTime) return left.startTime - right.startTime;
      return left.arrivalIndex - right.arrivalIndex;
    })
    .map(([key, segment]) => ({
      key,
      uid: segment.uid,
      startTime: segment.startTime,
      text: segment.text,
      textTs: segment.textTs,
      revision: segment.revision,
      arrivalIndex: segment.arrivalIndex,
      ...(segment.pendingFinal ? { pendingFinal: segment.pendingFinal } : {}),
    }));
}

function updateSentenceSegments(
  segments: Map<string, SentenceSegment>,
  candidate: ExtractedSttTranscript,
  arrivalIndex: number,
): SentenceUpdateResult {
  const timedKey = sentenceKey(candidate);
  const key = timedKey ?? provisionalSentenceKey(candidate);
  if (candidate.textTs == null) {
    return { text: rebuildSentenceTranscript(segments), action: "drop-missing-time-metadata", segments, sentencesCount: segments.size, reason: "missing textTs" };
  }

  const revision = transcriptRevision(candidate, arrivalIndex);
  const nextSegments = new Map(segments);
  if (timedKey) {
    nextSegments.delete(provisionalSentenceKey(candidate));
  }
  const segment = nextSegments.get(key);
  const startTime = timedKey ? candidate.time as number : Number.MAX_SAFE_INTEGER;
  if (candidate.final) {
    const pendingFinal = { text: candidate.text, textTs: candidate.textTs, revision, arrivalIndex };
    const shouldUseFinalText = !segment || !segment.text;
    nextSegments.set(key, segment
      ? {
          ...segment,
          text: shouldUseFinalText ? candidate.text : segment.text,
          textTs: shouldUseFinalText ? candidate.textTs : segment.textTs,
          revision: shouldUseFinalText ? revision : segment.revision,
          pendingFinal,
        }
      : {
          uid: transcriptUid(candidate),
          startTime,
          text: candidate.text,
          textTs: candidate.textTs,
          revision,
          arrivalIndex,
          pendingFinal,
        });
    return {
      text: rebuildSentenceTranscript(nextSegments),
      action: "hold-final-fragment",
      segments: nextSegments,
      sentenceKey: key,
      sentenceStartTime: startTime,
      existingTextTs: segment?.textTs,
      textTs: candidate.textTs,
      pendingFinalTextTs: candidate.textTs,
      pendingFinalLength: candidate.text.length,
      sentencesCount: nextSegments.size,
    };
  }

  if (segment) {
    const isOlderTextTs = candidate.textTs < segment.textTs;
    const isSameTextTsStaleRevision = candidate.textTs === segment.textTs && revision < segment.revision;
    if (isOlderTextTs || isSameTextTsStaleRevision) {
      return {
        text: rebuildSentenceTranscript(segments),
        action: "drop-stale-sentence",
        segments,
        sentenceKey: key,
        sentenceStartTime: candidate.time,
        existingTextTs: segment.textTs,
        textTs: candidate.textTs,
        sentencesCount: segments.size,
        reason: isOlderTextTs ? "older textTs" : "stale revision",
      };
    }
  }

  const appliedText = segment?.pendingFinal ? `${segment.pendingFinal.text}${candidate.text}` : candidate.text;

  nextSegments.set(key, {
    uid: transcriptUid(candidate),
    startTime,
    text: appliedText,
    textTs: candidate.textTs,
    revision,
    arrivalIndex: segment?.arrivalIndex ?? arrivalIndex,
  });
  return {
    text: rebuildSentenceTranscript(nextSegments),
    action: segment?.pendingFinal ? "replace-sentence-with-held-final" : segment ? "replace-sentence" : "create-sentence",
    segments: nextSegments,
    sentenceKey: key,
    sentenceStartTime: startTime,
    existingTextTs: segment?.textTs,
    textTs: candidate.textTs,
    pendingFinalTextTs: segment?.pendingFinal?.textTs,
    pendingFinalLength: segment?.pendingFinal?.text.length,
    heldFinalApplied: Boolean(segment?.pendingFinal),
    sentencesCount: nextSegments.size,
  };
}

type SttPhase =
  | "idle"
  | "preparing_rtc"
  | "joining_rtc"
  | "asr_bot_starting"
  | "ready_mic_off"
  | "draft_updating"
  | "error";

type SttResources = {
  rtcClient: any;
  micTrack: any;
  preparedSession: SttSessionPrepareResponse;
  sttSession: SttSessionStartResponse | null;
};

function DraftPanel({
  draftSession,
  streamingDraftText,
}: {
  draftSession: DraftSession | null;
  streamingDraftText: string;
}) {
  const draft = draftSession?.current_draft ?? null;
  const draftText = streamingDraftText || draft?.text || "";
  if (!draftText) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="text-[11px] uppercase tracking-[0.18em] text-primary">Current draft</div>
        <div className="mt-3 flex min-h-[240px] flex-1 items-center justify-center rounded-[24px] border border-dashed border-border/70 bg-white/45 p-5 text-center text-[14px] leading-7 text-muted-foreground">
          No draft yet. Hold the mic to start shaping one.
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto rounded-[24px] border border-white/75 bg-white/58 p-4">
      <div className="text-[11px] uppercase tracking-[0.18em] text-primary">Current draft</div>
      {draft?.last_update_summary ? <p className="mt-2 text-[12px] text-muted-foreground">{draft.last_update_summary}</p> : null}
      <div className="mt-4 rounded-[22px] bg-white/70 p-4">
        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Draft text</div>
        <p className="mt-2 whitespace-pre-wrap text-[14px] leading-7 text-foreground/82">{draftText}</p>
      </div>
    </div>
  );
}

export function BroDetailPage({
  bro,
  sessionId,
  activeTaskId,
  summary,
  taskRecords,
  agentEvents,
  snapshotDraftSession,
  latestDraftOutputEvent,
  onSubmitDraftAsrTurn,
  onBack,
  onGlobalError,
}: {
  bro: BroCardModel;
  sessionId: string | null;
  activeTaskId: string | null;
  summary: TaskSummary | null;
  taskRecords?: BroTaskRecord[];
  agentEvents?: AgentEvent[];
  snapshotDraftSession: DraftSession | null;
  latestDraftOutputEvent: DraftOutputEvent | null;
  onSubmitDraftAsrTurn?: (
    payload: {
      raw_text: string;
      normalized_text?: string;
      confidence?: number;
      assigned_bro_id?: string;
    },
  ) => string | null;
  onBack: () => void;
  onGlobalError?: (message: string | null) => void;
}) {
  const [sttPhase, setSttPhase] = useState<SttPhase>("idle");
  const [acceptedTranscript, setAcceptedTranscript] = useState("");
  const [draftSession, setDraftSession] = useState<DraftSession | null>(null);
  const [streamingDraftText, setStreamingDraftText] = useState("");
  const [micActive, setMicActive] = useState(false);
  const [sendingDraft, setSendingDraft] = useState(false);
  const [clearingDraft, setClearingDraft] = useState(false);
  const [draftActionError, setDraftActionError] = useState<string | null>(null);
  const [stoppingTask, setStoppingTask] = useState(false);
  const [taskActionError, setTaskActionError] = useState<string | null>(null);
  const [mobileDetailPage, setMobileDetailPage] = useState<MobileDetailPage>("draft");
  const resourcesRef = useRef<SttResources | null>(null);
  const submittedRef = useRef<Set<string>>(new Set());
  const acceptedTranscriptRef = useRef("");
  const sentenceSegmentsRef = useRef<Map<string, SentenceSegment>>(new Map());
  const transcriptArrivalIndexRef = useRef(0);
  const silenceCommitTimerRef = useRef<number | null>(null);
  const postReleaseMuteTimerRef = useRef<number | null>(null);
  const micCaptureStateRef = useRef<MicCaptureState>("muted");
  const releasedForDraftUpdateRef = useRef(false);
  const activePointerIdRef = useRef<number | null>(null);
  const mountedRef = useRef(false);
  const generationRef = useRef(0);
  const pendingDraftRequestIdRef = useRef<string | null>(null);

  const clearSilenceCommitTimer = useCallback(() => {
    if (silenceCommitTimerRef.current === null) return;
    window.clearTimeout(silenceCommitTimerRef.current);
    silenceCommitTimerRef.current = null;
  }, []);

  const clearPostReleaseMuteTimer = useCallback(() => {
    if (postReleaseMuteTimerRef.current === null) return;
    window.clearTimeout(postReleaseMuteTimerRef.current);
    postReleaseMuteTimerRef.current = null;
  }, []);

  const resetDraftWorkspace = useCallback(() => {
    clearSilenceCommitTimer();
    sentenceSegmentsRef.current = new Map();
    submittedRef.current = new Set();
    acceptedTranscriptRef.current = "";
    transcriptArrivalIndexRef.current = 0;
    releasedForDraftUpdateRef.current = false;
    pendingDraftRequestIdRef.current = null;
    setAcceptedTranscript("");
    setDraftSession(null);
    setStreamingDraftText("");
  }, [clearSilenceCommitTimer]);

  useEffect(() => {
    if (snapshotDraftSession === null) {
      setDraftSession(null);
      return;
    }
    setDraftSession(snapshotDraftSession);
  }, [snapshotDraftSession]);

  useEffect(() => {
    if (latestDraftOutputEvent === null) return;
    if (latestDraftOutputEvent.request_id !== pendingDraftRequestIdRef.current) return;

    if (latestDraftOutputEvent.type === "draft_output_started") {
      setStreamingDraftText("");
      setSttPhase("draft_updating");
      return;
    }
    if (latestDraftOutputEvent.type === "draft_output_delta") {
      setStreamingDraftText((current) => current + latestDraftOutputEvent.delta);
      return;
    }
    if (latestDraftOutputEvent.type === "draft_output_completed") {
      const draftText = latestDraftOutputEvent.draft_text;
      setStreamingDraftText(draftText);
      setDraftSession({
        id: latestDraftOutputEvent.draft_session_id,
        current_draft: {
          text: draftText,
        },
        status: "ready",
      });
      pendingDraftRequestIdRef.current = null;
      setSttPhase("ready_mic_off");
      return;
    }
    onGlobalError?.(latestDraftOutputEvent.message || "Failed to update draft from transcript.");
    pendingDraftRequestIdRef.current = null;
    setSttPhase("error");
  }, [latestDraftOutputEvent, onGlobalError]);

  const commitCurrentTranscript = useCallback(async (reason: "silence") => {
    clearSilenceCommitTimer();
    if (!releasedForDraftUpdateRef.current) return;
    const draftRawText = acceptedTranscriptRef.current;
    if (!draftRawText) return;
    setSttPhase("draft_updating");
    console.debug("[BroDetail][STT] commit reason", reason);
    console.debug("[BroDetail][STT] draft raw text", draftRawText);

    if (submittedRef.current.has(draftRawText)) {
      setSttPhase("ready_mic_off");
      return;
    }
    submittedRef.current.add(draftRawText);

    if (sessionId) {
      const requestId = onSubmitDraftAsrTurn?.({
        raw_text: draftRawText,
        assigned_bro_id: bro.id,
      }) ?? null;
      if (requestId !== null) {
        pendingDraftRequestIdRef.current = requestId;
        setStreamingDraftText("");
        return;
      }
      try {
        const nextDraftSession = await submitDraftAsrTurn(sessionId, {
          raw_text: draftRawText,
          assigned_bro_id: bro.id,
        });
        setDraftSession(nextDraftSession as DraftSession);
        setStreamingDraftText("");
        setSttPhase("ready_mic_off");
      } catch (error) {
        onGlobalError?.(error instanceof Error ? error.message : "Failed to update draft from transcript.");
        setSttPhase("error");
      }
    } else {
      setSttPhase("ready_mic_off");
    }
  }, [bro.id, clearSilenceCommitTimer, onGlobalError, onSubmitDraftAsrTurn, sessionId]);

  const scheduleSilenceCommit = useCallback(() => {
    if (!releasedForDraftUpdateRef.current) return;
    clearSilenceCommitTimer();
    silenceCommitTimerRef.current = window.setTimeout(() => {
      void commitCurrentTranscript("silence");
    }, STT_SILENCE_COMMIT_MS);
  }, [clearSilenceCommitTimer, commitCurrentTranscript]);

  const markHeldForDraftUpdate = useCallback(() => {
    releasedForDraftUpdateRef.current = false;
    clearSilenceCommitTimer();
  }, [clearSilenceCommitTimer]);

  const markReleasedForDraftUpdate = useCallback(() => {
    releasedForDraftUpdateRef.current = true;
    scheduleSilenceCommit();
  }, [scheduleSilenceCommit]);

  const schedulePostReleaseMute = useCallback(() => {
    clearPostReleaseMuteTimer();
    postReleaseMuteTimerRef.current = window.setTimeout(() => {
      postReleaseMuteTimerRef.current = null;
      if (micCaptureStateRef.current !== "tail") return;
      const micTrack = resourcesRef.current?.micTrack;
      if (!micTrack || sttPhase === "error") return;
      void Promise.resolve(micTrack.setMuted?.(true))
        .then(() => {
          if (micCaptureStateRef.current === "tail") {
            micCaptureStateRef.current = "muted";
          }
        })
        .catch((error: unknown) => {
          if (!mountedRef.current) return;
          onGlobalError?.(error instanceof Error ? error.message : "Failed to toggle microphone.");
          setSttPhase("error");
        });
    }, STT_RELEASE_AUDIO_TAIL_MS);
  }, [clearPostReleaseMuteTimer, onGlobalError, sttPhase]);

  const leaveResources = useCallback(async (resources: SttResources | null) => {
    if (!resources) return;
    clearPostReleaseMuteTimer();
    micCaptureStateRef.current = "muted";
    try {
      await resources.micTrack?.setMuted?.(true);
    } catch {}
    try {
      resources.micTrack?.stop?.();
      resources.micTrack?.close?.();
    } catch {}
    try {
      await resources.rtcClient?.leave?.();
    } catch {}
    try {
      if (resources.sttSession?.stt_session_id) {
        await leaveSttSession({ stt_session_id: resources.sttSession.stt_session_id });
      } else if (resources.preparedSession.prepared_stt_session_id) {
        await leaveSttSession({ prepared_stt_session_id: resources.preparedSession.prepared_stt_session_id });
      }
    } catch (error) {
      if (mountedRef.current) {
        onGlobalError?.(error instanceof Error ? error.message : "Failed to leave STT session.");
      }
    }
  }, [clearPostReleaseMuteTimer, onGlobalError]);

  const resetStaleSttResources = useCallback(async (message: string) => {
    const resources = resourcesRef.current;
    resourcesRef.current = null;
    clearSilenceCommitTimer();
    clearPostReleaseMuteTimer();
    micCaptureStateRef.current = "muted";
    setMicActive(false);
    setSttPhase("error");
    onGlobalError?.(message);
    if (!resources) return;
    try {
      await resources.micTrack?.setMuted?.(true);
    } catch {}
    try {
      resources.micTrack?.stop?.();
      resources.micTrack?.close?.();
    } catch {}
    try {
      await resources.rtcClient?.leave?.();
    } catch {}
  }, [clearPostReleaseMuteTimer, clearSilenceCommitTimer, onGlobalError]);

  const handleTranscript = useCallback(async (payload: unknown) => {
    const parsed = extractTranscriptText(payload);
    if (!parsed) {
      console.debug("[BroDetail][STT] ignored payload", payload);
      return;
    }
    const arrivalIndex = ++transcriptArrivalIndexRef.current;
    const update = updateSentenceSegments(sentenceSegmentsRef.current, parsed, arrivalIndex);
    console.debug("[BroDetail][STT] received candidate", {
      segments: serializeTranscriptSegmentsForDebug(update.segments),
      displayText: update.text,
      words: parsed.words ?? [],
      protobuf: describeProtobufTranscriptPayload(payload),
    });
    if (
      update.action === "create-sentence"
      || update.action === "replace-sentence"
      || update.action === "replace-sentence-with-held-final"
      || update.action === "hold-final-fragment"
    ) {
      sentenceSegmentsRef.current = update.segments;
      if (update.text !== acceptedTranscriptRef.current) {
        acceptedTranscriptRef.current = update.text;
        setAcceptedTranscript(update.text);
      }
    } else {
      return;
    }
    scheduleSilenceCommit();
  }, [scheduleSilenceCommit]);

  useEffect(() => {
    mountedRef.current = true;
    const generation = ++generationRef.current;
    let rtcClient: any | null = null;
    let micTrack: any | null = null;
    let preparedSession: SttSessionPrepareResponse | null = null;

    async function start() {
      if (!sessionId) return;
      setSttPhase("preparing_rtc");
      onGlobalError?.(null);
      try {
        preparedSession = await prepareSttSession({ synapse_session_id: sessionId, assigned_bro_id: bro.id });
        if (!mountedRef.current || generationRef.current !== generation) return;
        setSttPhase("joining_rtc");
        const { AgoraRTC } = await loadAgoraBrowserStack();
        rtcClient = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
        rtcClient.on?.("stream-message", (uid: string | number, payload: unknown) => {
          void handleTranscript(payload);
        });
        rtcClient.on?.("stream-message-error", (_uid: string | number, error: unknown) => {
          onGlobalError?.(error instanceof Error ? error.message : "Failed to receive STT transcript.");
        });
        await rtcClient.join(preparedSession.app_id, preparedSession.channel_name, preparedSession.token, preparedSession.uid);
        micTrack = await AgoraRTC.createMicrophoneAudioTrack();
        await rtcClient.publish([micTrack]);
        await micTrack.setMuted?.(true);
        micCaptureStateRef.current = "muted";
        resourcesRef.current = { rtcClient, micTrack, preparedSession, sttSession: null };
        if (!mountedRef.current || generationRef.current !== generation) return;
        setSttPhase("asr_bot_starting");
        const sttSession = await startSttSession({
          prepared_stt_session_id: preparedSession.prepared_stt_session_id,
        });
        resourcesRef.current = { rtcClient, micTrack, preparedSession, sttSession };
        if (!mountedRef.current || generationRef.current !== generation) return;
        setSttPhase("ready_mic_off");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to start STT session.";
        if (mountedRef.current && generationRef.current === generation) {
          onGlobalError?.(message);
          setSttPhase("error");
        }
        await leaveResources(
          preparedSession
            ? { rtcClient, micTrack, preparedSession, sttSession: resourcesRef.current?.sttSession ?? null }
            : null,
        );
      }
    }

    void start();

    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      clearSilenceCommitTimer();
      clearPostReleaseMuteTimer();
      const resources = resourcesRef.current;
      resourcesRef.current = null;
      void leaveResources(resources);
    };
  }, [bro.id, clearPostReleaseMuteTimer, clearSilenceCommitTimer, handleTranscript, leaveResources, onGlobalError, sessionId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const sttSessionId = resourcesRef.current?.sttSession?.stt_session_id;
      if (sttSessionId) {
        void heartbeatSttSession(sttSessionId).catch((error) => {
          if (mountedRef.current) {
            const message = error instanceof Error ? error.message : "Failed to heartbeat STT session.";
            if (message.includes("Unknown STT session")) {
              void resetStaleSttResources("STT session expired. Start voice again to create a fresh session.");
              return;
            }
            onGlobalError?.(message);
          }
        });
      }
    }, HEARTBEAT_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [onGlobalError, resetStaleSttResources]);

  async function setMicEnabled(enabled: boolean) {
    const micTrack = resourcesRef.current?.micTrack;
    if (!micTrack || sttPhase === "error") return;
    try {
      if (enabled) {
        if (micCaptureStateRef.current === "held") {
          setMicActive(true);
          return;
        }
        clearPostReleaseMuteTimer();
        markHeldForDraftUpdate();
        micCaptureStateRef.current = "held";
        setMicActive(true);
        await micTrack.setMuted?.(false);
        return;
      }
      if (micCaptureStateRef.current !== "held") {
        setMicActive(false);
        return;
      }
      setMicActive(false);
      micCaptureStateRef.current = "tail";
      markReleasedForDraftUpdate();
      schedulePostReleaseMute();
    } catch (error) {
      onGlobalError?.(error instanceof Error ? error.message : "Failed to toggle microphone.");
      setSttPhase("error");
    }
  }

  function handleMicPointerDown(event: PointerEvent<HTMLButtonElement>) {
    activePointerIdRef.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    void setMicEnabled(true);
  }

  function handleMicPointerUp(event: PointerEvent<HTMLButtonElement>) {
    activePointerIdRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    void setMicEnabled(false);
  }

  function handleMicKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.repeat || (event.key !== " " && event.key !== "Enter")) return;
    event.preventDefault();
    void setMicEnabled(true);
  }

  function handleMicKeyUp(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== " " && event.key !== "Enter") return;
    event.preventDefault();
    void setMicEnabled(false);
  }

  async function handleSendDraft() {
    if (!sessionId || !draftSession?.current_draft || sendingDraft || clearingDraft) return;
    setSendingDraft(true);
    setDraftActionError(null);
    onGlobalError?.(null);
    try {
      await sendDraft(sessionId, { draft_session_id: draftSession.id });
      resetDraftWorkspace();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to send draft to Bro.";
      setDraftActionError(message);
      onGlobalError?.(message);
    } finally {
      if (mountedRef.current) {
        setSendingDraft(false);
      }
    }
  }

  async function handleClearDraft() {
    if (!sessionId || !draftSession?.current_draft || sendingDraft || clearingDraft) return;
    setClearingDraft(true);
    setDraftActionError(null);
    onGlobalError?.(null);
    try {
      await clearDraft(sessionId, { draft_session_id: draftSession.id });
      resetDraftWorkspace();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to clear draft.";
      setDraftActionError(message);
      onGlobalError?.(message);
    } finally {
      if (mountedRef.current) {
        setClearingDraft(false);
      }
    }
  }

  async function handleStopTask() {
    if (!sessionId || !activeTaskId || stoppingTask) return;
    setStoppingTask(true);
    setTaskActionError(null);
    onGlobalError?.(null);
    try {
      await submitTaskCommand(sessionId, {
        command_type: "cancel_task",
        task_id: activeTaskId,
        reason: "Stopped from Bro detail Runner Brain.",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to stop task.";
      setTaskActionError(message);
      onGlobalError?.(message);
    } finally {
      if (mountedRef.current) {
        setStoppingTask(false);
      }
    }
  }

  const readyForMic = sttPhase === "ready_mic_off" || sttPhase === "draft_updating";
  const capturing = micActive;
  const transcriptText = acceptedTranscript;
  const draftReady = Boolean(draftSession?.current_draft);
  const draftActionPending = sendingDraft || clearingDraft;
  const canSendDraft = bro.source === "runtime";
  const draftText = streamingDraftText || draftSession?.current_draft?.text || "";
  const mobileTabClass = (page: MobileDetailPage) => (
    `min-h-[40px] flex-1 rounded-lg px-4 py-2 text-[12px] font-semibold uppercase tracking-[0.12em] transition ${
      mobileDetailPage === page
        ? "bg-[#fff0ec] text-[#ff6a3d]"
        : "bg-white text-[#6b7280] hover:bg-[#f1f3f5] hover:text-[#111827]"
    }`
  );

  const renderRunnerPanel = () => (
    <RunnerBrainPanel
      bro={bro}
      summary={summary}
      taskRecords={taskRecords}
      agentEvents={agentEvents}
      activeTaskId={activeTaskId}
      stoppingTask={stoppingTask}
      stopTaskError={taskActionError}
      onStopTask={() => {
        void handleStopTask();
      }}
    />
  );

  return (
    <div className="nb-detail-shell">
      <section className="nb-detail-main">
        <BroDetailHeader bro={bro} onBack={onBack} />
        <div
          className="mt-4 flex rounded-xl border border-[#e5e7eb] bg-white p-1 lg:hidden"
          role="tablist"
          aria-label="Bro detail sections"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mobileDetailPage === "draft"}
            className={mobileTabClass("draft")}
            onClick={() => setMobileDetailPage("draft")}
          >
            Draft
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileDetailPage === "status"}
            className={mobileTabClass("status")}
            onClick={() => setMobileDetailPage("status")}
          >
            Status
          </button>
        </div>
        <h2 className="sr-only">Draft workspace for {bro.name}</h2>

        <div className={`${mobileDetailPage === "draft" ? "flex" : "hidden"} mt-4 nb-detail-scroll nb-draft-tab-content lg:mt-0 lg:block`}>
            <DraftBrainPanel
              draftText={draftText}
              dispatchPlan={draftSession?.current_dispatch_plan ?? null}
              summary={draftSession?.current_draft?.last_update_summary}
              canSend={canSendDraft}
              sendDisabled={!sessionId || !draftReady || draftActionPending}
              clearDisabled={!sessionId || !draftReady || draftActionPending}
              sending={sendingDraft}
              clearing={clearingDraft}
              error={draftActionError}
              onSend={() => {
                void handleSendDraft();
              }}
              onClear={() => {
                void handleClearDraft();
              }}
            />

          <LiveTranscriptPanel active={capturing} transcriptText={transcriptText} />

            <VoicePad
              active={capturing}
              disabled={!sessionId || !readyForMic || sttPhase === "draft_updating" || draftActionPending}
              onPointerDown={handleMicPointerDown}
              onPointerUp={handleMicPointerUp}
              onPointerCancel={(event) => handleMicPointerUp(event)}
              onKeyDown={handleMicKeyDown}
              onKeyUp={handleMicKeyUp}
              onBlur={() => {
                if (activePointerIdRef.current === null) void setMicEnabled(false);
              }}
            />
        </div>
        {mobileDetailPage === "status" ? (
          <div className="mt-4 nb-detail-scroll lg:hidden">
            {renderRunnerPanel()}
          </div>
        ) : null}
      </section>

      <div className="hidden min-h-0 overflow-hidden lg:block">
        {renderRunnerPanel()}
      </div>
      </div>
  );
}
