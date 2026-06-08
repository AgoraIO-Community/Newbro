import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  bootstrapPublicUser,
  clearVoiceTarget,
  getConversationSnapshot,
  getCurrentUser,
  getSessionSnapshot,
  listBros,
  listBroThreadsPage,
  listBroTimelinePage,
  logoutPublicUser,
  openSessionStream,
  resolveInteractionRequest,
  sendSocketCommand,
  sendSocketDraftAsrTurn,
  sendSocketMessage,
  setVoiceTarget,
  signupPublicUser,
  subscribeBroThread,
  unsubscribeBroThread,
  type PublicUser,
} from "./lib/session-client";
import { beginThreadOpen, finishThreadOpen, threadOpenKey } from "./lib/thread-open-dedupe";
import { readSessionIdFromUrl, replaceSessionIdInUrl } from "./lib/session-url";
import { buildBroCardModels } from "./components/newbro/adapters";
import { useVoiceSession } from "./components/newbro/useVoiceSession";
import { Check, Mail } from "lucide-react";
import type {
  DraftOutputCompletedStreamEvent,
  DraftOutputDeltaStreamEvent,
  DraftOutputFailedStreamEvent,
  DraftOutputStartedStreamEvent,
  DraftSession,
  ExecutionDetailEntry,
  NativeReasoningStep,
  ExecutionSession,
  ExecutionRun,
  ExecutorNodeRecord,
  ExecutorSkill,
  AgentEvent,
  AttentionItem,
  BroListResponse,
  BroSummary,
  BroTimelineTurn,
  BroThread,
  BroThreadPageResponse,
  CursorPageInfo,
  InteractionRequest,
  Persona,
  SessionSnapshot,
  Task,
  TaskSummary,
} from "./types";

type DraftOutputEvent =
  | DraftOutputStartedStreamEvent
  | DraftOutputDeltaStreamEvent
  | DraftOutputCompletedStreamEvent
  | DraftOutputFailedStreamEvent;

const AUTH_REQUIRED_STATUS = "Request failed with status 401";
const AUTH_REQUIRED_MESSAGE = "Authentication required";

function logDirectExecutorSnapshotMetric(sessionId: string, snapshot: SessionSnapshot): void {
  const directTasks = snapshot.tasks
    .filter((task) => task.metadata.source_kind === "bro_detail_text" || typeof task.metadata.client_request_id === "string")
    .sort((left, right) => {
      const leftTime = Date.parse(String(left.metadata.updated_at ?? left.metadata.created_at ?? ""));
      const rightTime = Date.parse(String(right.metadata.updated_at ?? right.metadata.created_at ?? ""));
      if (!Number.isNaN(leftTime) && !Number.isNaN(rightTime)) return rightTime - leftTime;
      return 0;
    });
  const task = directTasks[0];
  if (!task) return;
  const run = snapshot.execution_runs.find((candidate) => candidate.task_id === task.task_id) ?? null;
  const payload = {
    stage: "ui.stream.snapshot.received",
    at: new Date().toISOString(),
    session_id: sessionId,
    client_request_id: task.metadata.client_request_id ?? null,
    instruction_id: task.metadata.instruction_id ?? null,
    task_id: task.task_id,
    task_status: task.status,
    run_id: run?.run_id ?? null,
    run_status: run?.status ?? null,
    target_thread_id: task.metadata.target_thread_id ?? null,
    created_at: task.metadata.created_at ?? null,
    updated_at: task.metadata.updated_at ?? null,
  };
  window.dispatchEvent(new CustomEvent("newbro:direct-executor-metric", { detail: payload }));
  if (import.meta.env.MODE !== "test") {
    // eslint-disable-next-line no-console
    console.info("[newbro:direct-executor]", payload);
  }
}

function isAuthRequiredError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.message.includes(AUTH_REQUIRED_STATUS) || error.message.includes(AUTH_REQUIRED_MESSAGE);
}

function describeApiFailure(error: unknown, defaultMessage: string): string {
  if (!(error instanceof Error)) {
    return defaultMessage;
  }

  const message = error.message.trim();
  if (!message) {
    return defaultMessage;
  }
  if (message.length > 240) {
    return defaultMessage;
  }
  if (/<(?:!doctype|html|body)/i.test(message)) {
    return defaultMessage;
  }
  return message;
}

function compactBroToPersona(bro: BroSummary): Persona {
  return {
    persona_id: bro.persona_id,
    name: bro.name,
    avatar: bro.avatar,
    base_prompt: "",
    executor_node_id: bro.executor_node?.node_id ?? null,
    bro_detail_session_id: bro.persona_id,
    status: bro.status,
  };
}

function compactBroToExecutorNode(bro: BroSummary): ExecutorNodeRecord | null {
  const node = bro.executor_node;
  if (!node) {
    return null;
  }
  const connectedCodex = node.connection_status === "connected" && node.codex !== null;
  return {
    node_id: node.node_id,
    name: node.name,
    enabled_executors: node.enabled_executors,
    acpx_agent: null,
    connected_executors: connectedCodex ? ["codex"] : [],
    connected_executor_capabilities: node.codex
      ? [
          {
            executor_type: "codex",
            supports_pause: false,
            supports_cancel: false,
            supports_resume: true,
            supports_follow_up: true,
            connected: connectedCodex,
            node_id: node.node_id,
            availability_reason: node.codex.availability_reason,
            supports_audio_instruction: node.codex.supports_audio_instruction,
            supports_thread_list: node.codex.supports_thread_list,
          },
        ]
      : [],
    connection_status: node.connection_status,
    token_hint: null,
    last_connected_at: node.last_connected_at,
    last_seen_at: null,
  };
}

function personasFromBroList(response: BroListResponse): Persona[] {
  return response.bros.map(compactBroToPersona);
}

function executorNodesFromBroList(response: BroListResponse): ExecutorNodeRecord[] {
  const nodesById = new Map<string, ExecutorNodeRecord>();
  for (const bro of response.bros) {
    const node = compactBroToExecutorNode(bro);
    if (node) {
      nodesById.set(node.node_id, node);
    }
  }
  return [...nodesById.values()];
}

function upsertThread(threads: BroThread[], thread: BroThread): BroThread[] {
  let replaced = false;
  const next = threads.map((candidate) => {
    if (candidate.thread_id !== thread.thread_id) {
      return candidate;
    }
    replaced = true;
    return thread;
  });
  return replaced ? next : [thread, ...next];
}

function markThreadTimeline(
  threads: BroThread[],
  threadId: string,
  status: BroThread["timeline_status"],
  error: string | null = null,
): BroThread[] {
  return threads.map((thread) => (
    thread.thread_id === threadId
      ? { ...thread, timeline_status: status, timeline_error: error }
      : thread
  ));
}

function isExecutorConnectionErrorMessage(value: string | null | undefined): boolean {
  const normalized = (value ?? "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return normalized.includes("executor node is not connected")
    || normalized.includes("executor node not connected");
}

function clearExecutorConnectionTimelineErrors(threads: BroThread[]): BroThread[] {
  let changed = false;
  const next = threads.map((thread) => {
    if (
      thread.timeline_status !== "failed"
      || !isExecutorConnectionErrorMessage(thread.timeline_error)
    ) {
      return thread;
    }
    changed = true;
    return { ...thread, timeline_status: "not_loaded" as const, timeline_error: null };
  });
  return changed ? next : threads;
}

function replaceTimelineTurnsForThread(
  turns: BroTimelineTurn[],
  threadId: string,
  nextTurns: BroTimelineTurn[],
): BroTimelineTurn[] {
  return [
    ...turns.filter((turn) => turn.thread_id !== threadId),
    ...nextTurns,
  ];
}

function prependTimelineTurns(
  turns: BroTimelineTurn[],
  nextTurns: BroTimelineTurn[],
): BroTimelineTurn[] {
  const seen = new Set(turns.map((turn) => turn.turn_id));
  return [...nextTurns.filter((turn) => !seen.has(turn.turn_id)), ...turns];
}

function broCanListThreads(bro: BroSummary): boolean {
  return Boolean(
    bro.executor_node
    && bro.executor_node.connection_status === "connected"
    && bro.executor_node.codex?.supports_thread_list,
  );
}

function SignupInviteCodeInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const normalized = value.replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 8);
  const cellCount = 8;

  return (
    <div
      className="ob-invite-row nb-signup-invite-row"
      role="group"
      aria-label="Invitation code"
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        aria-label="Invitation code"
        className="nb-signup-invite-input"
        value={normalized}
        onChange={(event) => onChange(event.target.value.replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 8))}
        autoComplete="one-time-code"
        inputMode="text"
        maxLength={8}
        pattern="[A-Za-z0-9]{8}"
        spellCheck={false}
      />
      {Array.from({ length: cellCount }).map((_, index) => {
        const char = normalized[index] ?? "";
        const filled = char.length > 0;
        const cursor = Math.min(normalized.length, cellCount - 1) === index;
        return (
          <span key={index} className="nb-signup-invite-cell-wrap">
            <span className={`ob-invite-cell${filled ? " ob-invite-cell-on" : ""}${cursor ? " ob-invite-cell-cur" : ""}`}>
              <span className="ob-invite-glyph">{char}</span>
              {cursor ? <span className="ob-invite-caret" aria-hidden="true" /> : null}
            </span>
            {index === 3 && index !== cellCount - 1 ? <span className="ob-invite-sep" aria-hidden="true">–</span> : null}
          </span>
        );
      })}
    </div>
  );
}

function SignupPanel({
  error,
  onSignup,
}: {
  error: string | null;
  onSignup: (email: string, code: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const normalizedCode = code.replace(/[^a-z0-9]/gi, "").toUpperCase().slice(0, 8);
  const canSubmit = email.trim().length > 0 && /^[A-Z0-9]{8}$/.test(normalizedCode) && !submitting;
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    void onSignup(email.trim(), normalizedCode).finally(() => setSubmitting(false));
  };

  return (
    <div className="dt-frame nb-signup-shell min-h-dvh text-[#111827]">
      <div className="dt-signin-bg hidden md:block" aria-hidden="true" />

      <div className="dt-signin-brand hidden md:flex">
        <div className="dt-signin-brand-tile">
          <img src="/newbro.webp" alt="" draggable={false} />
        </div>
        <span className="ob-wordmark">
          <span className="ob-wordmark-text">newbro</span>
          <span className="ob-wordmark-build">alpha</span>
        </span>
        <span className="dt-signin-build">build 0.4.2 · closed alpha</span>
      </div>

      <div className="ob-page ob-signin nb-signup-card min-h-dvh w-full overflow-hidden border-0 shadow-none">
        <header className="ob-signin-bar md:hidden">
          <div className="ob-signin-logo">
            <img src="/newbro.webp" alt="" draggable={false} />
          </div>
          <span className="ob-wordmark">
            <span className="ob-wordmark-text">newbro</span>
            <span className="ob-wordmark-build">alpha</span>
          </span>
          <span className="ob-signin-build">0.4.2</span>
        </header>

        <main className="ob-signin-main md:contents">
          <section className="dt-signin-card-l hidden md:flex">
            <span className="ob-eyebrow ob-eyebrow-coral">INVITATION ONLY</span>
            <h1 className="dt-h1">Hi there.<br />Let's get you in.</h1>
            <p className="dt-sub">
              Newbro is a small crew of bros — each one lives on a computer you trust and keeps working while you talk. No setup headaches.
            </p>
            <ul className="dt-signin-bullets">
              <li><span className="dt-signin-bullet-dot" /><span>One workspace per email.</span></li>
              <li><span className="dt-signin-bullet-dot" /><span>Connect your own computers — a Mac, a spare laptop, anything that stays on.</span></li>
              <li><span className="dt-signin-bullet-dot" /><span>Voice-first — no passwords, just invitation tokens.</span></li>
            </ul>
          </section>

          <section className="md:hidden">
            <span className="ob-eyebrow ob-eyebrow-coral">INVITATION ONLY · CLOSED ALPHA</span>
            <h1 className="ob-h1">Hi there.<br />Let's get you in.</h1>
            <p className="ob-sub">
              Newbro is a small crew of bros — each one lives on a computer you trust and keeps working while you talk. No setup headaches.
            </p>
          </section>

          <form className="ob-form nb-signup-desktop-form" onSubmit={handleSubmit}>
            <label className="ob-field">
              <span className="ob-field-eyebrow">YOUR EMAIL</span>
              <span className={`ob-input${email.trim() ? " ob-input-filled" : ""}`}>
                <span className="ob-input-icon" aria-hidden="true">
                  <Mail size={15} strokeWidth={1.9} />
                </span>
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  type="email"
                />
                {email.trim() ? (
                  <span className="ob-input-check" aria-hidden="true">
                    <Check size={11} strokeWidth={2.6} />
                  </span>
                ) : null}
              </span>
              <span className="ob-field-hint">This becomes your workspace handle.</span>
            </label>
            <label className="ob-field">
              <span className="ob-field-eyebrow">INVITATION CODE</span>
              <SignupInviteCodeInput value={code} onChange={setCode} />
              <span className="ob-field-hint">From the email we sent — 8 characters, case-insensitive.</span>
            </label>
            <button disabled={!canSubmit} className="ob-cta ob-cta-block nb-signup-desktop-cta" type="submit">
              <span>{submitting ? "Opening..." : "Continue"}</span>
              {!submitting ? <kbd className="ob-cta-kbd">↵</kbd> : null}
            </button>
            {error ? <div className="text-[13px] leading-6 text-red-600">{error}</div> : null}
            <div className="ob-foot">
              <span>Don't have an invite?</span>
              <button type="button" className="ob-link">Request access</button>
            </div>
          </form>
        </main>
        <footer className="ob-signin-footer nb-signup-footer">
          <span className="ob-mono-tiny">no accounts · no passwords · invitation tokens only</span>
        </footer>
      </div>
    </div>
  );
}

function useNewbroShellState() {
  const [runtimePersonas, setRuntimePersonas] = useState<Persona[]>([]);
  const [executorNodes, setExecutorNodes] = useState<ExecutorNodeRecord[]>([]);
  const [broSkillsMap, setBroSkillsMap] = useState<Record<string, ExecutorSkill[]>>({});
  const [tasks, setTasks] = useState<Task[]>([]);
  const [executionSessions, setExecutionSessions] = useState<ExecutionSession[]>([]);
  const [executionRuns, setExecutionRuns] = useState<ExecutionRun[]>([]);
  const [broThreads, setBroThreads] = useState<BroThread[]>([]);
  const [broTimelineTurns, setBroTimelineTurns] = useState<BroTimelineTurn[]>([]);
  const [broThreadPages, setBroThreadPages] = useState<Record<string, CursorPageInfo>>({});
  const [broTimelinePages, setBroTimelinePages] = useState<Record<string, CursorPageInfo>>({});
  const [interactionRequests, setInteractionRequests] = useState<InteractionRequest[]>([]);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [taskSummaries, setTaskSummaries] = useState<TaskSummary[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [recentExecutionDetails, setRecentExecutionDetails] = useState<Record<string, ExecutionDetailEntry[]>>({});
  const [recentNativeTurnReasoning, setRecentNativeTurnReasoning] = useState<Record<string, NativeReasoningStep[]>>({});
  const [activeShellSessionId, setActiveShellSessionId] = useState<string | null>(null);
  const [defaultPersonaId, setDefaultPersonaId] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<PublicUser | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [hasLoadedShellSnapshot, setHasLoadedShellSnapshot] = useState(false);
  const [shellError, setShellError] = useState<string | null>(null);
  const [shellWarning, setShellWarning] = useState<string | null>(null);
  const [threadOpenError, setThreadOpenError] = useState<string | null>(null);
  const [openingThreadId, setOpeningThreadId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; text: string; id: string; createdAt?: string }>>([]);
  const [draftSession, setDraftSession] = useState<DraftSession | null>(null);
  const [latestDraftOutputEvent, setLatestDraftOutputEvent] = useState<DraftOutputEvent | null>(null);
  const [streamReconnectNonce, setStreamReconnectNonce] = useState(0);
  const mountedRef = useRef(false);
  const shellLoadSequenceRef = useRef(0);
  const broListRefreshSequenceRef = useRef(0);
  const threadOpenInFlightRef = useRef(new Set<string>());
  const threadOpenLatestKeyRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const streamReconnectTimerRef = useRef<number | null>(null);
  const streamSessionIdRef = useRef<string | null>(null);
  const streamOpenedForSessionRef = useRef(false);

  function applySnapshot(snapshot: SessionSnapshot) {
    setTasks(snapshot.tasks ?? []);
    setExecutionSessions(snapshot.execution_sessions ?? []);
    setExecutionRuns(snapshot.execution_runs ?? []);
    setBroThreads(snapshot.bro_threads ?? []);
    setBroTimelineTurns(snapshot.bro_timeline_turns ?? []);
    setInteractionRequests(snapshot.interaction_requests ?? []);
    setAttentionItems(snapshot.attention_items ?? []);
    setTaskSummaries(snapshot.summaries ?? []);
    setAgentEvents(snapshot.agent_events ?? []);
    setRecentExecutionDetails(snapshot.recent_execution_details ?? {});
    setRecentNativeTurnReasoning(snapshot.recent_native_turn_reasoning ?? {});
    setDraftSession(snapshot.draft_session ?? null);
    setHasLoadedShellSnapshot(true);
    setShellError(null);
  }

  function applyBroList(response: BroListResponse) {
    setRuntimePersonas(personasFromBroList(response));
    setExecutorNodes(executorNodesFromBroList(response));
    const skillsMap: Record<string, ExecutorSkill[]> = {};
    for (const bro of response.bros) {
      skillsMap[bro.persona_id] = bro.executor_node?.codex?.skills ?? [];
    }
    setBroSkillsMap(skillsMap);
  }

  function applyBroThreadPages(pages: BroThreadPageResponse[]) {
    if (pages.length === 0) {
      return;
    }
    setBroThreads((current) => {
      let next = current;
      for (const page of pages) {
        for (const thread of page.threads) {
          next = upsertThread(next, thread);
        }
      }
      return next;
    });
    setBroThreadPages((current) => {
      const next = { ...current };
      for (const page of pages) {
        next[page.persona_id] = page.page;
      }
      return next;
    });
  }

  function clearShellSessionState() {
    setRuntimePersonas([]);
    setExecutorNodes([]);
    setBroSkillsMap({});
    setTasks([]);
    setExecutionSessions([]);
    setExecutionRuns([]);
    setBroThreads([]);
    setBroTimelineTurns([]);
    setBroThreadPages({});
    setBroTimelinePages({});
    setInteractionRequests([]);
    setAttentionItems([]);
    setTaskSummaries([]);
    setAgentEvents([]);
    setActiveShellSessionId(null);
    setDefaultPersonaId(null);
    setCurrentUser(null);
    setHasLoadedShellSnapshot(false);
    setShellError(null);
    setShellWarning(null);
    setThreadOpenError(null);
    setOpeningThreadId(null);
    setChatMessages([]);
    setDraftSession(null);
    setLatestDraftOutputEvent(null);
  }

  const loadShellSession = useEffectEvent(async (sessionId: string) => {
    if (!mountedRef.current) {
      return;
    }
    const loadSequence = ++shellLoadSequenceRef.current;
    setShellError(null);
    const [snapshot, conversation, broList] = await Promise.all([
      getSessionSnapshot(sessionId),
      getConversationSnapshot(sessionId),
      listBros(sessionId),
    ]);
    const broThreadPages = await Promise.all(
      broList.bros
        .filter(broCanListThreads)
        .map(async (bro) => {
          try {
            return await listBroThreadsPage(sessionId, {
              targetPersonaId: bro.persona_id,
              cursor: null,
              limit: 15,
            });
          } catch (error) {
            return {
              persona_id: bro.persona_id,
              threads: [],
              page: {
                next_cursor: null,
                previous_cursor: null,
                has_more: false,
                status: "failed" as const,
                error: describeApiFailure(error, "Thread list could not be loaded."),
              },
            };
          }
        }),
    );
    if (!mountedRef.current || shellLoadSequenceRef.current !== loadSequence) {
      return;
    }
    startTransition(() => {
      setActiveShellSessionId(sessionId);
      applySnapshot(snapshot);
      applyBroList(broList);
      applyBroThreadPages(broThreadPages);
      const hydrated = (conversation.conversation_history ?? []).map((entry) => ({
        role: entry.role as "user" | "assistant",
        text: entry.text,
        id: entry.message_id,
        createdAt: entry.created_at,
      }));
      setChatMessages(hydrated);
    });
  });

  const { state: voiceSession, start, stop, toggleMute } = useVoiceSession();

  const bootstrapHostedUser = useEffectEvent(async () => {
    const bootstrap = await bootstrapPublicUser();
    setCurrentUser(bootstrap.user);
    setDefaultPersonaId(bootstrap.default_persona_id);
    replaceSessionIdInUrl(bootstrap.session_id);
    await loadShellSession(bootstrap.session_id);
  });

  const refreshShellSession = useEffectEvent(async () => {
    if (!activeShellSessionId) {
      return;
    }
    await loadShellSession(activeShellSessionId);
  });

  const refreshBroList = useEffectEvent(async (sessionId: string) => {
    if (!mountedRef.current) {
      return;
    }
    const loadSequence = shellLoadSequenceRef.current;
    const refreshSequence = ++broListRefreshSequenceRef.current;
    try {
      const broList = await listBros(sessionId);
      if (
        !mountedRef.current
        || activeShellSessionId !== sessionId
        || shellLoadSequenceRef.current !== loadSequence
        || broListRefreshSequenceRef.current !== refreshSequence
      ) {
        return;
      }
      startTransition(() => {
        applyBroList(broList);
        setThreadOpenError((current) => (
          isExecutorConnectionErrorMessage(current) ? null : current
        ));
        setShellError((current) => (
          isExecutorConnectionErrorMessage(current) ? null : current
        ));
        setShellWarning((current) => (
          isExecutorConnectionErrorMessage(current) ? null : current
        ));
        setBroThreads((current) => clearExecutorConnectionTimelineErrors(current));
      });
    } catch (error: unknown) {
      if (!mountedRef.current || activeShellSessionId !== sessionId) {
        return;
      }
      startTransition(() => {
        setShellWarning(describeApiFailure(error, "Bro connection status could not refresh."));
      });
    }
  });

  const openRuntimeBroThread = useEffectEvent(async (targetPersonaId: string, threadId: string) => {
    if (!activeShellSessionId || !mountedRef.current) {
      return;
    }
    const openKey = threadOpenKey(targetPersonaId, threadId);
    threadOpenLatestKeyRef.current = openKey;
    setOpeningThreadId(threadId);
    setThreadOpenError(null);
    if (beginThreadOpen(threadOpenInFlightRef.current, targetPersonaId, threadId) === null) {
      return;
    }
    try {
      setBroThreads((current) => markThreadTimeline(current, threadId, "loading"));
      // Subscribe (live updates) runs concurrently with the timeline fetch and must not
      // block the visible history; a subscribe failure only loses live attach.
      void subscribeBroThread(activeShellSessionId, { targetPersonaId, threadId }).catch((error) => {
        console.warn("bro thread subscribe failed", error);
      });
      const page = await listBroTimelinePage(activeShellSessionId, {
        targetPersonaId,
        threadId,
        cursor: null,
        limit: 15,
      });
      if (!mountedRef.current || threadOpenLatestKeyRef.current !== openKey) {
        return;
      }
      startTransition(() => {
        setBroThreads((current) => upsertThread(current, page.thread));
        setBroTimelineTurns((current) => replaceTimelineTurnsForThread(current, threadId, page.turns));
        setBroTimelinePages((current) => ({ ...current, [threadId]: page.page }));
      });
    } catch (error) {
      if (!mountedRef.current || threadOpenLatestKeyRef.current !== openKey) {
        return;
      }
      setBroThreads((current) => markThreadTimeline(current, threadId, "failed", describeApiFailure(error, "Thread history could not be fetched. Try selecting the thread again.")));
      setThreadOpenError(describeApiFailure(error, "Thread history could not be fetched. Try selecting the thread again."));
    } finally {
      finishThreadOpen(threadOpenInFlightRef.current, openKey);
      if (mountedRef.current) {
        setOpeningThreadId((current) => (current === threadId ? null : current));
      }
    }
  });

  const closeRuntimeBroThread = useEffectEvent(async (targetPersonaId: string, threadId: string | null) => {
    if (!activeShellSessionId || !threadId || !mountedRef.current) {
      return;
    }
    try {
      await unsubscribeBroThread(activeShellSessionId, { targetPersonaId, threadId });
      if (!mountedRef.current) {
        return;
      }
      startTransition(() => {
        setBroThreads((current) => markThreadTimeline(current, threadId, "not_loaded"));
        setBroTimelinePages((current) => {
          const { [threadId]: _removed, ...rest } = current;
          return rest;
        });
      });
    } catch {
      // Closing a selected thread is cleanup; backend subscription ids still
      // protect the newly selected thread if this request fails.
    }
  });

  const loadMoreBroThreads = useEffectEvent(async (targetPersonaId: string) => {
    if (!activeShellSessionId || !mountedRef.current) {
      return;
    }
    const pageInfo = broThreadPages[targetPersonaId];
    if (!pageInfo?.next_cursor) {
      return;
    }
    try {
      const page = await listBroThreadsPage(activeShellSessionId, {
        targetPersonaId,
        cursor: pageInfo.next_cursor,
        limit: 15,
      });
      if (!mountedRef.current) {
        return;
      }
      startTransition(() => {
        setBroThreads((current) => {
          const seen = new Set(current.map((thread) => thread.thread_id));
          return [...current, ...page.threads.filter((thread) => !seen.has(thread.thread_id))];
        });
        setBroThreadPages((current) => ({ ...current, [targetPersonaId]: page.page }));
      });
    } catch (error) {
      if (mountedRef.current) {
        setShellError(describeApiFailure(error, "More threads could not be loaded."));
      }
    }
  });

  const loadMoreBroTimeline = useEffectEvent(async (targetPersonaId: string, threadId: string) => {
    if (!activeShellSessionId || !mountedRef.current) {
      return;
    }
    const pageInfo = broTimelinePages[threadId];
    if (!pageInfo?.next_cursor) {
      return;
    }
    try {
      const page = await listBroTimelinePage(activeShellSessionId, {
        targetPersonaId,
        threadId,
        cursor: pageInfo.next_cursor,
        limit: 15,
      });
      if (!mountedRef.current) {
        return;
      }
      startTransition(() => {
        setBroTimelineTurns((current) => {
          return prependTimelineTurns(current, page.turns);
        });
        setBroThreads((current) => upsertThread(current, page.thread));
        setBroTimelinePages((current) => ({ ...current, [threadId]: page.page }));
      });
    } catch (error) {
      if (mountedRef.current) {
        setShellError(describeApiFailure(error, "Older timeline entries could not be loaded."));
      }
    }
  });

  useEffect(() => {
    mountedRef.current = true;

    async function bootstrapShell() {
      const requestedSessionId = readSessionIdFromUrl();
      if (requestedSessionId) {
        try {
          await loadShellSession(requestedSessionId);
          const me = await getCurrentUser();
          if (!mountedRef.current) {
            return;
          }
          startTransition(() => {
            setCurrentUser(me.user);
            setShellWarning(null);
          });
          return;
        } catch {
          try {
            await bootstrapHostedUser();
            return;
          } catch (error: unknown) {
            if (!mountedRef.current) {
              return;
            }
            if (isAuthRequiredError(error)) {
              startTransition(() => {
                setAuthRequired(true);
                setAuthError(null);
                clearShellSessionState();
              });
              return;
            }
            startTransition(() => {
              setActiveShellSessionId(null);
              setHasLoadedShellSnapshot(false);
              setShellWarning(null);
              setShellError(
                describeApiFailure(error, "Session bootstrap failed before the shell could start."),
              );
            });
            return;
          }
        }
      }

      try {
        await bootstrapHostedUser();
        if (!mountedRef.current) {
          return;
        }
        startTransition(() => setShellWarning(null));
      } catch (error: unknown) {
        if (!mountedRef.current) {
          return;
        }
        if (isAuthRequiredError(error)) {
          startTransition(() => {
            setAuthRequired(true);
            setAuthError(null);
            clearShellSessionState();
          });
          return;
        }
        startTransition(() => {
          setActiveShellSessionId(null);
          setHasLoadedShellSnapshot(false);
          setShellWarning(null);
          setShellError(
            describeApiFailure(error, "Session bootstrap failed before the shell could start."),
          );
        });
      }
    }
    void bootstrapShell();
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!activeShellSessionId) {
      if (streamReconnectTimerRef.current !== null) {
        window.clearTimeout(streamReconnectTimerRef.current);
        streamReconnectTimerRef.current = null;
      }
      socketRef.current = null;
      streamSessionIdRef.current = null;
      streamOpenedForSessionRef.current = false;
      return undefined;
    }
    if (streamSessionIdRef.current !== activeShellSessionId) {
      streamSessionIdRef.current = activeShellSessionId;
      streamOpenedForSessionRef.current = false;
    }
    let closedByCleanup = false;
    const scheduleReconnect = () => {
      if (!mountedRef.current || streamReconnectTimerRef.current !== null) {
        return;
      }
      streamReconnectTimerRef.current = window.setTimeout(() => {
        streamReconnectTimerRef.current = null;
        if (mountedRef.current) {
          setStreamReconnectNonce((current) => current + 1);
        }
      }, 1000);
    };
    const socket = openSessionStream(activeShellSessionId, {
      onOpen: () => {
        if (streamOpenedForSessionRef.current) {
          void refreshBroList(activeShellSessionId);
        }
        streamOpenedForSessionRef.current = true;
      },
      onClose: () => {
        socketRef.current = null;
        if (!closedByCleanup) {
          scheduleReconnect();
        }
      },
      onError: () => {
        socketRef.current = null;
        if (!closedByCleanup) {
          scheduleReconnect();
        }
      },
      onMessage: (event) => {
        if (!mountedRef.current) return;
        if (event.type === "bro_list_invalidated") {
          void refreshBroList(activeShellSessionId);
          return;
        }
        if (event.type === "snapshot") {
          logDirectExecutorSnapshotMetric(activeShellSessionId, event.snapshot);
          startTransition(() => applySnapshot(event.snapshot));
          return;
        }
        if (
          event.type === "draft_output_started"
          || event.type === "draft_output_delta"
          || event.type === "draft_output_completed"
          || event.type === "draft_output_failed"
        ) {
          startTransition(() => setLatestDraftOutputEvent(event));
          return;
        }
        if (event.type === "user_message_appended") {
          startTransition(() => {
            setChatMessages((prev) => {
              if (prev.some((m) => m.id === event.message_id)) return prev;
              return [
                ...prev,
                { role: "user" as const, text: event.text, id: event.message_id, createdAt: event.created_at },
              ];
            });
          });
          return;
        }
        if (event.type === "assistant_response_completed") {
          startTransition(() => {
            setChatMessages((prev) => {
              if (prev.some((m) => m.id === event.message_id)) return prev;
              return [
                ...prev,
                { role: "assistant" as const, text: event.reply_text, id: event.message_id, createdAt: event.created_at },
              ];
            });
          });
          return;
        }
        if (event.type === "conversation_appended") {
          startTransition(() => {
            setChatMessages((prev) => {
              // Deduplicate — assistant_response_completed may have already added this
              if (prev.some((m) => m.id === event.message_id)) return prev;
              return [
                ...prev,
                { role: "assistant" as const, text: event.text, id: event.message_id, createdAt: event.created_at },
              ];
            });
          });
        }
      },
    });
    socketRef.current = socket;
    return () => {
      closedByCleanup = true;
      if (streamReconnectTimerRef.current !== null) {
        window.clearTimeout(streamReconnectTimerRef.current);
        streamReconnectTimerRef.current = null;
      }
      socket.close();
      socketRef.current = null;
    };
  }, [activeShellSessionId, streamReconnectNonce]);

  useEffect(() => {
    if (!activeShellSessionId) {
      return;
    }
    replaceSessionIdInUrl(activeShellSessionId);
  }, [activeShellSessionId]);

  const bros = useMemo(
    () => buildBroCardModels(runtimePersonas, executorNodes, executionRuns, taskSummaries, tasks, recentExecutionDetails),
    [executorNodes, executionRuns, runtimePersonas, taskSummaries, tasks, recentExecutionDetails],
  );

  const clearGlobalMessage = useEffectEvent(() => {
    setShellError(null);
    setShellWarning(null);
  });

  const sendMessage = useCallback((text: string, targetPersonaId?: string | null): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const requestId = `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sendSocketMessage(socket, requestId, text, targetPersonaId);
    return true;
  }, []);

  const cancelTask = useCallback((taskId: string): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const requestId = `cancel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sendSocketCommand(socket, requestId, "cancel_task", taskId);
    return true;
  }, []);

  const submitDraftAsrTurn = useCallback((payload: {
    raw_text: string;
    normalized_text?: string;
    confidence?: number;
    assigned_bro_id?: string;
  }): string | null => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return null;
    const requestId = `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sendSocketDraftAsrTurn(socket, requestId, payload);
    return requestId;
  }, []);

  const resolveShellInteractionRequest = useCallback(async (
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
  ): Promise<void> => {
    if (!activeShellSessionId) return;
    await resolveInteractionRequest(activeShellSessionId, interactionRequestId, payload);
    await loadShellSession(activeShellSessionId);
  }, [activeShellSessionId, loadShellSession]);

  const startMobileVoiceSession = useEffectEvent(async (targetBroId: string | null) => {
    if (!activeShellSessionId) {
      setShellWarning("Voice needs an active session before it can start.");
      return;
    }
    if (runtimePersonas.length === 0) {
      setShellWarning("Create a Bro before starting voice.");
      return;
    }
    const targetBro = targetBroId ? bros.find((bro) => bro.id === targetBroId) ?? null : null;
    if (targetBro && targetBro.liveState !== "live") {
      setShellWarning(
        targetBro.liveState === "offline"
          ? `${targetBro.name}'s computer is offline. Reconnect it before starting this channel.`
          : `${targetBro.name} needs a computer before voice can target it.`,
      );
      return;
    }
    try {
      if (targetBroId) {
        await setVoiceTarget(activeShellSessionId, targetBroId);
      } else {
        await clearVoiceTarget(activeShellSessionId).catch(() => undefined);
      }
      await start(activeShellSessionId);
      if (mountedRef.current) {
        startTransition(() => setShellWarning(null));
      }
    } catch (error: unknown) {
      if (!mountedRef.current) return;
      startTransition(() => {
        setShellError(describeApiFailure(error, "Mobile voice could not start."));
      });
    }
  });

  const stopMobileVoiceSession = useEffectEvent(async () => {
    const sessionId = activeShellSessionId;
    try {
      await stop();
      if (sessionId) {
        await clearVoiceTarget(sessionId).catch(() => undefined);
      }
    } catch (error: unknown) {
      if (!mountedRef.current) return;
      startTransition(() => {
        setShellError(describeApiFailure(error, "Mobile voice could not stop cleanly."));
      });
    }
  });

  const signupWithCode = useEffectEvent(async (email: string, code: string) => {
    setAuthError(null);
    try {
      await signupPublicUser(email, code);
      if (!mountedRef.current) return;
      await bootstrapHostedUser();
      if (!mountedRef.current) return;
      startTransition(() => {
        setAuthRequired(false);
        setAuthError(null);
        setShellWarning(null);
      });
    } catch (error: unknown) {
      if (!mountedRef.current) return;
      startTransition(() => {
        setAuthError(describeApiFailure(error, "Signup could not be completed."));
      });
    }
  });

  const logout = useEffectEvent(async () => {
    if (logoutPending) {
      return;
    }
    setLogoutPending(true);
    setShellError(null);
    try {
      try {
        await stop();
      } catch {
        // Keep logout authoritative even if local voice teardown already failed.
      }
      socketRef.current?.close();
      socketRef.current = null;
      await logoutPublicUser();
      if (!mountedRef.current) return;
      replaceSessionIdInUrl(null);
      startTransition(() => {
        clearShellSessionState();
        setAuthRequired(true);
        setAuthError(null);
      });
    } catch (error: unknown) {
      if (!mountedRef.current) return;
      startTransition(() => {
        setShellError(describeApiFailure(error, "Logout could not be completed."));
      });
    } finally {
      if (mountedRef.current) {
        setLogoutPending(false);
      }
    }
  });

  return {
    bros,
    voiceSession,
    activeShellSessionId,
    defaultPersonaId,
    currentUser,
    logoutPending,
    authRequired,
    authError,
    hasLoadedShellSnapshot,
    runtimePersonas,
    executorNodes,
    broSkillsMap,
    tasks,
    executionSessions,
    executionRuns,
    broThreads,
    broTimelineTurns,
    broThreadPages,
    broTimelinePages,
    interactionRequests,
    attentionItems,
    taskSummaries,
    agentEvents,
    recentExecutionDetails,
    recentNativeTurnReasoning,
    shellError,
    shellWarning,
    threadOpenError,
    openingThreadId,
    setShellError,
    clearGlobalMessage,
    startVoiceSession: start,
    stopVoiceSession: stop,
    toggleVoiceMute: toggleMute,
    startMobileVoiceSession,
    stopMobileVoiceSession,
    sendMessage,
    cancelTask,
    submitDraftAsrTurn,
    resolveInteractionRequest: resolveShellInteractionRequest,
    signupWithCode,
    logout,
    refreshShellSession,
    openRuntimeBroThread,
    closeRuntimeBroThread,
    loadMoreBroThreads,
    loadMoreBroTimeline,
    draftSession,
    latestDraftOutputEvent,
    chatMessages,
  };
}

type NewbroShellState = ReturnType<typeof useNewbroShellState>;

const NewbroShellContext = createContext<NewbroShellState | null>(null);

function isActiveArtboardPath(pathname: string): boolean {
  return pathname === "/" || pathname === "/mobile" || pathname.startsWith("/bros/");
}

export function NewbroShellProvider({ children }: { children: ReactNode }) {
  const value = useNewbroShellState();
  if (value.authRequired) {
    if (!isActiveArtboardPath(window.location.pathname)) return null;
    return <SignupPanel error={value.authError} onSignup={value.signupWithCode} />;
  }
  return (
    <NewbroShellContext.Provider value={value}>
      {children}
    </NewbroShellContext.Provider>
  );
}

export function useNewbroShell() {
  const value = useContext(NewbroShellContext);
  if (value === null) {
    throw new Error("Newbro shell state is unavailable outside NewbroShellProvider.");
  }
  return value;
}
