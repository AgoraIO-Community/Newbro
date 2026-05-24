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
  type ReactNode,
} from "react";
import {
  bootstrapPublicUser,
  clearVoiceTarget,
  getConversationSnapshot,
  getSessionSnapshot,
  openSessionStream,
  sendSocketDraftAsrTurn,
  sendSocketMessage,
  setVoiceTarget,
  signupPublicUser,
} from "./lib/session-client";
import { readSessionIdFromUrl, replaceSessionIdInUrl } from "./lib/session-url";
import { BroDetailPage } from "./components/newbro/BroDetailPage";
import { BrosPage } from "./components/newbro/BrosPage";
import { BrosPanel } from "./components/newbro/BrosPanel";
import { MobileWalkie } from "./components/newbro/mobile/MobileWalkie";
import { NodesPage } from "./components/newbro/NodesPage";
import { Sidebar, type PageId } from "./components/newbro/Sidebar";
import { TopVoiceBar } from "./components/newbro/TopVoiceBar";
import { buildBroCardModels, buildBroTaskRecords } from "./components/newbro/adapters";
import { useVoiceSession } from "./components/newbro/useVoiceSession";
import { WindowDots } from "./components/newbro/visual";
import type {
  DraftOutputCompletedStreamEvent,
  DraftOutputDeltaStreamEvent,
  DraftOutputFailedStreamEvent,
  DraftOutputStartedStreamEvent,
  DraftSession,
  ExecutionRun,
  ExecutorNodeRecord,
  AgentEvent,
  Persona,
  SessionSnapshot,
  Task,
  TaskSummary,
} from "./types";

export type PageNavigator = (page: PageId) => void;
export type BroNavigator = (broId: string) => void;

type DraftOutputEvent =
  | DraftOutputStartedStreamEvent
  | DraftOutputDeltaStreamEvent
  | DraftOutputCompletedStreamEvent
  | DraftOutputFailedStreamEvent;

const SHELL_API_ERROR_TITLE = "Unable to reach the Newbro API";
const SHELL_API_ERROR_HINT =
  "This deployment must proxy /api/* requests to the backend before the shell can load live data.";
const RESUME_FALLBACK_WARNING_PREFIX = "Could not resume the requested session.";
const GLOBAL_MESSAGE_AUTO_DISMISS_MS = 6_000;
const AUTH_REQUIRED_STATUS = "Request failed with status 401";
const AUTH_REQUIRED_MESSAGE = "Authentication required";

function isAuthRequiredError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.message.includes(AUTH_REQUIRED_STATUS) || error.message.includes(AUTH_REQUIRED_MESSAGE);
}

function describeApiFailure(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  const message = error.message.trim();
  if (!message) {
    return fallback;
  }
  if (message.length > 240) {
    return fallback;
  }
  if (/<(?:!doctype|html|body)/i.test(message)) {
    return fallback;
  }
  return message;
}

function ShellApiErrorPanel({ detail }: { detail: string }) {
  return (
    <div
      data-testid="shell-api-error"
      className="paper-panel mx-4 my-4 rounded-[30px] border border-white/80 px-6 py-6 shadow-[0_24px_54px_-40px_rgba(15,23,42,0.22)] md:mx-6 md:my-6 xl:mx-8 xl:my-8"
    >
      <div className="text-[11px] uppercase tracking-[0.24em] text-[#8d5a62]">Connection problem</div>
      <div className="serif-flow mt-3 text-[32px] tracking-[-0.05em] text-foreground">
        {SHELL_API_ERROR_TITLE}
      </div>
      <div className="mt-3 max-w-[720px] text-[14px] leading-7 text-foreground/82">{detail}</div>
      <div className="mt-3 max-w-[720px] text-[13px] leading-6 text-muted-foreground">{SHELL_API_ERROR_HINT}</div>
    </div>
  );
}

function ShellLoadingPanel() {
  return (
    <div
      data-testid="shell-connecting"
      className="glass-panel mx-4 my-4 rounded-[30px] border border-white/80 px-6 py-6 text-[14px] text-muted-foreground md:mx-6 md:my-6 xl:mx-8 xl:my-8"
    >
      Connecting to session…
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
  const canSubmit = email.trim().length > 0 && code.trim().length > 0 && !submitting;
  return (
    <div className="page-wash flex min-h-dvh items-center justify-center bg-[#f5f6f8] px-4 text-[#111827]">
      <div className="paper-panel w-full max-w-[420px] rounded-[30px] border border-white/80 px-6 py-6 shadow-[0_24px_54px_-40px_rgba(15,23,42,0.22)]">
        <div className="text-[11px] uppercase tracking-[0.24em] text-[#8d5a62]">Sign up</div>
        <div className="serif-flow mt-3 text-[32px] tracking-[-0.05em] text-foreground">Newbro</div>
        <form
          className="mt-5 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            setSubmitting(true);
            void onSignup(email.trim(), code.trim()).finally(() => setSubmitting(false));
          }}
        >
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="Email"
            className="command-field w-full px-4 py-3 text-[14px] outline-none"
            autoComplete="email"
            type="email"
          />
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="Invitation code"
            className="command-field w-full px-4 py-3 text-[14px] outline-none"
            autoComplete="one-time-code"
          />
          <button disabled={!canSubmit} className="nb-page-primary-action w-full" type="submit">
            {submitting ? "Opening..." : "Enter"}
          </button>
          {error ? <div className="text-[13px] leading-6 text-red-600">{error}</div> : null}
        </form>
      </div>
    </div>
  );
}

type GlobalMessage = {
  detail: string;
  tone: "error" | "warning";
};

function GlobalMessageBanner({ message, onDismiss }: { message: GlobalMessage; onDismiss: () => void }) {
  const toneClass = message.tone === "error"
    ? "border-red-200 bg-red-50 text-red-600"
    : "border-amber-200 bg-amber-50 text-amber-700";

  useEffect(() => {
    const timer = window.setTimeout(onDismiss, GLOBAL_MESSAGE_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [message.detail, message.tone, onDismiss]);

  return (
    <div
      data-testid="global-message"
      className={`fixed inset-x-4 top-[calc(4.75rem+env(safe-area-inset-top))] z-50 rounded-2xl border px-4 py-3 pr-10 text-[13px] leading-6 shadow-[0_20px_60px_-32px_rgba(15,23,42,0.45)] backdrop-blur sm:left-auto sm:right-5 sm:top-5 sm:max-w-[420px] md:right-7 md:top-7 ${toneClass}`}
      role="status"
    >
      <div>{message.detail}</div>
      <button
        type="button"
        aria-label="Dismiss message"
        className="absolute right-3 top-2 text-[18px] leading-none opacity-55 transition hover:opacity-90"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  );
}

function buildResumeFallbackWarning(sessionId: string) {
  return `${RESUME_FALLBACK_WARNING_PREFIX} Opened a new session instead of ${sessionId}.`;
}

function globalMessageFor(shell: Pick<NewbroShellState, "shellError" | "shellWarning" | "hasLoadedShellSnapshot">): GlobalMessage | null {
  if (shell.shellError && shell.hasLoadedShellSnapshot) {
    return { detail: shell.shellError, tone: "error" };
  }
  if (shell.shellWarning) {
    return { detail: shell.shellWarning, tone: "warning" };
  }
  return null;
}

function useNewbroShellState() {
  const [runtimePersonas, setRuntimePersonas] = useState<Persona[]>([]);
  const [executorNodes, setExecutorNodes] = useState<ExecutorNodeRecord[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [executionRuns, setExecutionRuns] = useState<ExecutionRun[]>([]);
  const [taskSummaries, setTaskSummaries] = useState<TaskSummary[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [activeShellSessionId, setActiveShellSessionId] = useState<string | null>(null);
  const [defaultPersonaId, setDefaultPersonaId] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [hasLoadedShellSnapshot, setHasLoadedShellSnapshot] = useState(false);
  const [shellError, setShellError] = useState<string | null>(null);
  const [shellWarning, setShellWarning] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<Array<{ role: "user" | "assistant"; text: string; id: string }>>([]);
  const [draftSession, setDraftSession] = useState<DraftSession | null>(null);
  const [latestDraftOutputEvent, setLatestDraftOutputEvent] = useState<DraftOutputEvent | null>(null);
  const mountedRef = useRef(false);
  const shellLoadSequenceRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  function applySnapshot(snapshot: SessionSnapshot) {
    setRuntimePersonas(snapshot.personas);
    setExecutorNodes(snapshot.executor_nodes ?? []);
    setTasks(snapshot.tasks ?? []);
    setExecutionRuns(snapshot.execution_runs ?? []);
    setTaskSummaries(snapshot.summaries ?? []);
    setAgentEvents(snapshot.agent_events ?? []);
    setDraftSession(snapshot.draft_session ?? null);
    setHasLoadedShellSnapshot(true);
    setShellError(null);
  }

  const loadShellSession = useEffectEvent(async (sessionId: string) => {
    const loadSequence = ++shellLoadSequenceRef.current;
    setShellError(null);
    const [snapshot, conversation] = await Promise.all([
      getSessionSnapshot(sessionId),
      getConversationSnapshot(sessionId),
    ]);
    if (!mountedRef.current || shellLoadSequenceRef.current !== loadSequence) {
      return;
    }
    startTransition(() => {
      setActiveShellSessionId(sessionId);
      applySnapshot(snapshot);
      const hydrated = (conversation.conversation_history ?? []).map((entry) => ({
        role: entry.role as "user" | "assistant",
        text: entry.text,
        id: entry.message_id,
      }));
      setChatMessages(hydrated);
    });
  });

  const { state: voiceSession, start, stop, toggleMute } = useVoiceSession();

  const bootstrapHostedUser = useEffectEvent(async () => {
    const bootstrap = await bootstrapPublicUser();
    setDefaultPersonaId(bootstrap.default_persona_id);
    replaceSessionIdInUrl(bootstrap.session_id);
    await loadShellSession(bootstrap.session_id);
  });

  useEffect(() => {
    mountedRef.current = true;

    async function bootstrapShell() {
      const requestedSessionId = readSessionIdFromUrl();
      if (requestedSessionId) {
        try {
          await loadShellSession(requestedSessionId);
          if (!mountedRef.current) {
            return;
          }
          startTransition(() => setShellWarning(null));
          return;
        } catch {
          try {
            await bootstrapHostedUser();
            if (!mountedRef.current) {
              return;
            }
            startTransition(() => {
              setShellWarning(buildResumeFallbackWarning(requestedSessionId));
            });
            return;
          } catch (error: unknown) {
            if (!mountedRef.current) {
              return;
            }
            if (isAuthRequiredError(error)) {
              startTransition(() => {
                setAuthRequired(true);
                setAuthError(null);
                setActiveShellSessionId(null);
                setHasLoadedShellSnapshot(false);
                setShellWarning(null);
                setShellError(null);
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
            setActiveShellSessionId(null);
            setHasLoadedShellSnapshot(false);
            setShellWarning(null);
            setShellError(null);
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
      socketRef.current = null;
      return undefined;
    }
    const socket = openSessionStream(activeShellSessionId, {
      onOpen: () => {},
      onClose: () => { socketRef.current = null; },
      onError: () => { socketRef.current = null; },
      onMessage: (event) => {
        if (!mountedRef.current) return;
        if (event.type === "snapshot") {
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
                { role: "user" as const, text: event.text, id: event.message_id },
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
                { role: "assistant" as const, text: event.reply_text, id: event.message_id },
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
                { role: "assistant" as const, text: event.text, id: event.message_id },
              ];
            });
          });
        }
      },
    });
    socketRef.current = socket;
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [activeShellSessionId]);

  useEffect(() => {
    if (!activeShellSessionId) {
      return;
    }
    replaceSessionIdInUrl(activeShellSessionId);
  }, [activeShellSessionId]);

  const bros = useMemo(
    () => buildBroCardModels(runtimePersonas, executorNodes, executionRuns, taskSummaries, tasks),
    [executorNodes, executionRuns, runtimePersonas, taskSummaries, tasks],
  );

  const clearGlobalMessage = useEffectEvent(() => {
    setShellError(null);
    setShellWarning(null);
  });

  const sendMessage = useCallback((text: string): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    const requestId = `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    sendSocketMessage(socket, requestId, text);
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

  return {
    bros,
    voiceSession,
    activeShellSessionId,
    defaultPersonaId,
    authRequired,
    authError,
    hasLoadedShellSnapshot,
    runtimePersonas,
    executorNodes,
    tasks,
    executionRuns,
    taskSummaries,
    agentEvents,
    shellError,
    shellWarning,
    setShellError,
    clearGlobalMessage,
    startVoiceSession: start,
    stopVoiceSession: stop,
    toggleVoiceMute: toggleMute,
    sendMessage,
    submitDraftAsrTurn,
    signupWithCode,
    draftSession,
    latestDraftOutputEvent,
    chatMessages,
  };
}

type NewbroShellState = ReturnType<typeof useNewbroShellState>;

const NewbroShellContext = createContext<NewbroShellState | null>(null);

export function NewbroShellProvider({ children }: { children: ReactNode }) {
  const value = useNewbroShellState();
  if (value.authRequired) {
    return <SignupPanel error={value.authError} onSignup={value.signupWithCode} />;
  }
  return (
    <NewbroShellContext.Provider value={value}>
      {children}
    </NewbroShellContext.Provider>
  );
}

function useNewbroShell() {
  const value = useContext(NewbroShellContext);
  if (value === null) {
    throw new Error("Newbro shell state is unavailable outside NewbroShellProvider.");
  }
  return value;
}

function ShellVoiceBar() {
  const shell = useNewbroShell();
  if (!shell.hasLoadedShellSnapshot || !shell.activeShellSessionId) {
    return null;
  }

  return (
    <div className="px-4 pt-4 md:px-6 xl:px-8">
      <TopVoiceBar
        bros={shell.bros}
        voicePhase={shell.voiceSession.phase}
        error={shell.voiceSession.error}
        isMicMuted={shell.voiceSession.isMicMuted}
        messageCount={shell.voiceSession.transcript.length}
        sessionId={shell.activeShellSessionId}
        onStart={() => {
          void shell.startVoiceSession(shell.activeShellSessionId);
        }}
        onStop={() => {
          void shell.stopVoiceSession();
        }}
        onToggleMute={() => {
          void shell.toggleVoiceMute();
        }}
      />
    </div>
  );
}

function ShellFrame({
  activePage,
  onNavigate,
  globalMessage,
  onGlobalMessageDismiss,
  broCount,
  nodeCount,
  children,
}: {
  activePage: PageId;
  onNavigate: PageNavigator;
  globalMessage?: GlobalMessage | null;
  onGlobalMessageDismiss?: () => void;
  broCount: number;
  nodeCount: number;
  children: ReactNode;
}) {
  return (
    <div className="page-wash min-h-dvh overflow-x-hidden bg-[#f5f6f8] text-[#111827] antialiased">
      <WindowDots />
      <div className="grid min-h-dvh grid-cols-1 grid-rows-[auto_minmax(0,1fr)] lg:h-dvh lg:grid-cols-[248px_minmax(0,1fr)] lg:grid-rows-none lg:overflow-hidden">
        <Sidebar
          activePage={activePage}
          onNavigate={onNavigate}
          broCount={broCount}
          nodeCount={nodeCount}
        />
        <main data-testid="newbro-shell" className="relative flex min-h-0 min-w-0 flex-col overflow-x-hidden bg-[#fafbfc] lg:overflow-hidden">
          {children}
        </main>
        {globalMessage && onGlobalMessageDismiss ? (
          <GlobalMessageBanner message={globalMessage} onDismiss={onGlobalMessageDismiss} />
        ) : null}
      </div>
    </div>
  );
}

export function HomeShellPage({
  onNavigate,
  onBroNavigate,
}: {
  onNavigate: PageNavigator;
  onBroNavigate?: BroNavigator;
}) {
  const shell = useNewbroShell();
  if (shell.hasLoadedShellSnapshot && shell.defaultPersonaId) {
    return <BroDetailShellPage broId={shell.defaultPersonaId} onNavigate={onNavigate} />;
  }

  return (
    <ShellFrame
      activePage="Home"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
    >

      {shell.hasLoadedShellSnapshot ? (
        <div className="nb-detail-shell nb-detail-shell-full">
          <section className="nb-detail-main">
            <div className="nb-detail-topbar">
              <div className="nb-detail-crumb">
                <span>Workspace</span>
                <span className="nb-detail-crumb-sep">/</span>
                <span className="nb-detail-crumb-current">Home</span>
              </div>
            </div>
            <div className="nb-detail-bro-header">
              <div className="nb-detail-bro-title">
                <h1>Command Center</h1>
                <span className="nb-chip nb-chip-online">
                  <span className="nb-pulse" />
                  Runtime standby
                </span>
                <span className="nb-chip">{shell.runtimePersonas.length} Bros</span>
                <span className="nb-chip">{shell.executorNodes.length} Nodes</span>
              </div>
            </div>
            <div className="nb-detail-scroll space-y-5 sm:space-y-6">
              <div>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="command-label text-[#9ca3af]">Runtime Bros</div>
                  <span className="nb-chip">{shell.bros.length} visible</span>
                </div>
                <BrosPanel
                  bros={shell.bros}
                  sessionId={shell.activeShellSessionId}
                  onBroClick={(broId) => {
                    onBroNavigate?.(broId);
                  }}
                />
              </div>
            </div>
          </section>
        </div>
      ) : shell.shellError ? (
        <ShellApiErrorPanel detail={shell.shellError} />
      ) : (
        <ShellLoadingPanel />
      )}
    </ShellFrame>
  );
}

export function MobileWalkieShellPage() {
  const shell = useNewbroShell();
  const globalMessage = globalMessageFor(shell);

  if (shell.hasLoadedShellSnapshot) {
    return (
      <>
        <MobileWalkie bros={shell.bros} onSubmitMessage={shell.sendMessage} />
        {globalMessage ? (
          <GlobalMessageBanner message={globalMessage} onDismiss={shell.clearGlobalMessage} />
        ) : null}
      </>
    );
  }

  if (shell.shellError) {
    return (
      <div className="nb-mobile-stage">
        <ShellApiErrorPanel detail={shell.shellError} />
      </div>
    );
  }

  return (
    <div className="nb-mobile-stage">
      <ShellLoadingPanel />
    </div>
  );
}


export function BroDetailShellPage({
  broId,
  onNavigate,
}: {
  broId: string;
  onNavigate: PageNavigator;
}) {
  const shell = useNewbroShell();
  const bro = shell.bros.find((candidate) => candidate.id === broId) ?? null;
  const activeSummary = bro?.source === "runtime"
    ? shell.taskSummaries.find((summary) => summary.task_id === shell.runtimePersonas.find((persona) => persona.persona_id === bro.id)?.current_task_id) ?? null
    : null;
  const activePersona = bro?.source === "runtime"
    ? shell.runtimePersonas.find((persona) => persona.persona_id === bro.id) ?? null
    : null;
  const taskRecords = bro?.source === "runtime"
    ? buildBroTaskRecords(bro.id, {
        activeTaskId: activePersona?.current_task_id ?? null,
        broDetailSessionId: activePersona?.bro_detail_session_id ?? null,
        tasks: shell.tasks,
        executionRuns: shell.executionRuns,
        summaries: shell.taskSummaries,
      })
    : [];

  useEffect(() => {
    if (!shell.hasLoadedShellSnapshot || !shell.activeShellSessionId || !bro) {
      return undefined;
    }
    const sessionId = shell.activeShellSessionId;
    void setVoiceTarget(sessionId, bro.id).catch((error: unknown) => {
      shell.setShellError(describeApiFailure(error, "Could not bind voice to this Bro."));
    });
    return () => {
      void clearVoiceTarget(sessionId).catch(() => {});
    };
  }, [shell.hasLoadedShellSnapshot, shell.activeShellSessionId, bro?.id]);

  return (
    <ShellFrame
      activePage="Home"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
    >
      {shell.hasLoadedShellSnapshot ? (
        bro ? (
          <>
            <ShellVoiceBar />
            <BroDetailPage
              bro={bro}
              sessionId={shell.activeShellSessionId}
              activeTaskId={activePersona?.current_task_id ?? null}
              summary={activeSummary}
              taskRecords={taskRecords}
              agentEvents={shell.agentEvents.filter((event) => event.task_id === activePersona?.current_task_id)}
              snapshotDraftSession={shell.draftSession}
              latestDraftOutputEvent={shell.latestDraftOutputEvent}
              onSubmitDraftAsrTurn={shell.submitDraftAsrTurn}
              onBack={() => onNavigate("Home")}
              onGlobalError={shell.setShellError}
            />
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="glass-panel max-w-[520px] rounded-[30px] border border-white/75 px-6 py-6 text-center">
              <div className="serif-flow text-[32px] tracking-[-0.05em]">Bro not found</div>
              <p className="mt-3 text-[14px] leading-7 text-muted-foreground">
                This Bro is not available in the current session.
              </p>
              <button
                type="button"
                className="mt-5 rounded-full border border-border/70 bg-white/70 px-4 py-2 text-[14px]"
                onClick={() => onNavigate("Home")}
              >
                Back home
              </button>
            </div>
          </div>
        )
      ) : shell.shellError ? (
        <ShellApiErrorPanel detail={shell.shellError} />
      ) : (
        <ShellLoadingPanel />
      )}
    </ShellFrame>
  );
}

export function BrosShellPage({ onNavigate }: { onNavigate: PageNavigator }) {
  const shell = useNewbroShell();

  return (
    <ShellFrame
      activePage="Bros"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
    >
      {shell.activeShellSessionId && shell.hasLoadedShellSnapshot ? (
        <BrosPage
          sessionId={shell.activeShellSessionId}
          initialPersonas={shell.runtimePersonas}
          initialNodes={shell.executorNodes}
        />
      ) : shell.shellError ? (
        <ShellApiErrorPanel detail={shell.shellError} />
      ) : (
        <ShellLoadingPanel />
      )}
    </ShellFrame>
  );
}

export function NodesShellPage({ onNavigate }: { onNavigate: PageNavigator }) {
  const shell = useNewbroShell();

  return (
    <ShellFrame
      activePage="Nodes"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
    >
      {shell.activeShellSessionId && shell.hasLoadedShellSnapshot ? (
        <NodesPage
          sessionId={shell.activeShellSessionId}
          initialNodes={shell.executorNodes}
          initialPersonas={shell.runtimePersonas}
        />
      ) : shell.shellError ? (
        <ShellApiErrorPanel detail={shell.shellError} />
      ) : (
        <ShellLoadingPanel />
      )}
    </ShellFrame>
  );
}

export function SettingsShellPage({ onNavigate }: { onNavigate: PageNavigator }) {
  const shell = useNewbroShell();

  return (
    <ShellFrame
      activePage="Settings"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
    >
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="text-[14px] text-neutral-400">Settings coming soon.</div>
      </div>
    </ShellFrame>
  );
}
