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
  buildExecutorRunCommand,
  bootstrapPublicUser,
  clearVoiceTarget,
  createExecutorNode,
  createPersona,
  getConversationSnapshot,
  getCurrentUser,
  getSessionSnapshot,
  logoutPublicUser,
  openSessionStream,
  revealExecutorNodeConnectCommand,
  sendSocketDraftAsrTurn,
  sendSocketMessage,
  setVoiceTarget,
  signupPublicUser,
  updatePersona,
  type PublicUser,
} from "./lib/session-client";
import { readSessionIdFromUrl, replaceSessionIdInUrl } from "./lib/session-url";
import { BroDetailPage } from "./components/newbro/BroDetailPage";
import { BrosPage } from "./components/newbro/BrosPage";
import { BrosPanel } from "./components/newbro/BrosPanel";
import { MobileWalkie } from "./components/newbro/mobile/MobileWalkie";
import { NodesPage } from "./components/newbro/NodesPage";
import type { PageId } from "./components/newbro/Sidebar";
import { TopVoiceBar } from "./components/newbro/TopVoiceBar";
import { buildBroCardModels, buildBroTaskRecords } from "./components/newbro/adapters";
import { useVoiceSession } from "./components/newbro/useVoiceSession";
import { BroDetailHeader } from "./components/newbro/visual";
import { Check, Copy, Home, LoaderCircle, LogOut, Plus, Search, Server, Settings, Users, X } from "lucide-react";
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
import type { BroCardModel } from "./components/newbro/types";

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
      <div className="text-[11px] uppercase tracking-normal text-[#8d5a62]">Connection problem</div>
      <div className="serif-flow mt-3 text-[32px] tracking-normal text-foreground">
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

function SignupInviteCodeInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const normalized = value.toUpperCase();
  const cellCount = Math.max(8, Math.min(12, normalized.length || 8));

  return (
    <div
      className={`ob-invite-row nb-signup-invite-row${cellCount > 8 ? " nb-signup-invite-row-long" : ""}`}
      role="group"
      aria-label="Invitation code"
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        aria-label="Invitation code"
        className="nb-signup-invite-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="one-time-code"
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
            {index === 3 && index !== cellCount - 1 ? <span className="ob-invite-sep" aria-hidden="true">-</span> : null}
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
  const canSubmit = email.trim().length > 0 && code.trim().length > 0 && !submitting;
  return (
    <div className="dt-frame flex min-h-dvh items-stretch justify-center px-0 py-0 text-[#111827] md:items-center md:px-4 md:py-8">
      <div className="ob-page ob-signin min-h-dvh w-full overflow-hidden border-0 shadow-none md:h-auto md:min-h-[620px] md:max-w-[430px] md:rounded-[32px] md:border md:border-[#e5e7eb] md:shadow-[0_30px_70px_-30px_rgba(16,17,20,0.26)]">
        <header className="ob-signin-bar">
          <div className="ob-signin-logo">
            <img src="/newbro.webp" alt="" draggable={false} />
          </div>
          <span className="ob-wordmark">
            <span className="ob-wordmark-text">newbro</span>
            <span className="ob-wordmark-build">alpha</span>
          </span>
          <span className="ob-signin-build">Sign up</span>
        </header>
        <main className="ob-signin-main">
          <span className="ob-eyebrow ob-eyebrow-coral">INVITATION ONLY · CLOSED ALPHA</span>
          <h1 className="ob-h1">Hi there.<br />Let's get you in.</h1>
          <p className="ob-sub">
            Newbro is a small crew of bros — each one bound to an executor on a machine you trust.
            They keep working while you keep talking.
          </p>
        <form
          className="ob-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            setSubmitting(true);
            void onSignup(email.trim(), code.trim()).finally(() => setSubmitting(false));
          }}
        >
          <label className="ob-field">
            <span className="ob-field-eyebrow">YOUR EMAIL</span>
            <span className={`ob-input${email.trim() ? " ob-input-filled" : ""}`}>
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
            <span className="ob-field-hint">From the email we sent — case-insensitive.</span>
          </label>
          <button disabled={!canSubmit} className="ob-cta ob-cta-block" type="submit">
            <span>{submitting ? "Opening..." : "Continue"}</span>
            {!submitting ? <kbd className="ob-cta-kbd">↵</kbd> : null}
          </button>
          {error ? <div className="text-[13px] leading-6 text-red-600">{error}</div> : null}
        </form>
        </main>
        <footer className="ob-signin-footer">
          <span className="ob-mono-tiny">no passwords · invitation tokens only</span>
        </footer>
      </div>
    </div>
  );
}

type GlobalMessage = {
  detail: string;
  tone: "error" | "warning";
};

type BroNodeState =
  | {
      kind: "sample" | "no_bound_node" | "bound_node_missing";
      node: null;
    }
  | {
      kind: "never_connected" | "usable_disconnected" | "usable_connected";
      node: ExecutorNodeRecord;
    };

function hasNodeEverConnected(node: ExecutorNodeRecord): boolean {
  return Boolean(node.last_connected_at);
}

function deriveBroNodeState(
  bro: BroCardModel | null,
  nodes: ExecutorNodeRecord[],
): BroNodeState {
  if (!bro || bro.source !== "runtime") {
    return { kind: "sample", node: null };
  }
  if (!bro.executorNodeId) {
    return { kind: "no_bound_node", node: null };
  }
  const node = nodes.find((candidate) => candidate.node_id === bro.executorNodeId) ?? null;
  if (!node) {
    return { kind: "bound_node_missing", node: null };
  }
  if (!hasNodeEverConnected(node)) {
    return { kind: "never_connected", node };
  }
  if (node.connection_status === "connected") {
    return { kind: "usable_connected", node };
  }
  return { kind: "usable_disconnected", node };
}

function nodeStateRequiresSetup(state: BroNodeState): boolean {
  return state.kind === "no_bound_node" || state.kind === "bound_node_missing" || state.kind === "never_connected";
}

function nodeStateAllowsVoice(state: BroNodeState): boolean {
  return state.kind === "sample" || state.kind === "usable_connected";
}

function disconnectedNodeWarning(node: ExecutorNodeRecord): string {
  return `${node.name} is not connected. Run or reconnect the local executor command before talking to this Bro.`;
}

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
  const [currentUser, setCurrentUser] = useState<PublicUser | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);
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

  function clearShellSessionState() {
    setRuntimePersonas([]);
    setExecutorNodes([]);
    setTasks([]);
    setExecutionRuns([]);
    setTaskSummaries([]);
    setAgentEvents([]);
    setActiveShellSessionId(null);
    setDefaultPersonaId(null);
    setCurrentUser(null);
    setHasLoadedShellSnapshot(false);
    setShellError(null);
    setShellWarning(null);
    setChatMessages([]);
    setDraftSession(null);
    setLatestDraftOutputEvent(null);
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
          ? `${targetBro.name}'s node is offline. Reconnect it before starting this channel.`
          : `${targetBro.name} needs an executor node before voice can target it.`,
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
    startMobileVoiceSession,
    stopMobileVoiceSession,
    sendMessage,
    submitDraftAsrTurn,
    signupWithCode,
    logout,
    refreshShellSession,
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

function ShellVoiceBar({
  startDisabled = false,
  blockReason,
}: {
  startDisabled?: boolean;
  blockReason?: string | null;
}) {
  const shell = useNewbroShell();
  if (!shell.hasLoadedShellSnapshot || !shell.activeShellSessionId) {
    return null;
  }
  const emptyCrewBlockReason = shell.runtimePersonas.length === 0
    ? "Create a Bro before starting voice."
    : null;
  const effectiveStartDisabled = startDisabled || Boolean(emptyCrewBlockReason);
  const effectiveBlockReason = blockReason ?? emptyCrewBlockReason;

  return (
    <div>
      <TopVoiceBar
        bros={shell.bros}
        voicePhase={shell.voiceSession.phase}
        error={shell.voiceSession.error}
        isMicMuted={shell.voiceSession.isMicMuted}
        messageCount={shell.voiceSession.transcript.length}
        sessionId={shell.activeShellSessionId}
        startDisabled={effectiveStartDisabled}
        blockReason={effectiveBlockReason}
        onStart={() => {
          if (effectiveStartDisabled) return;
          void shell.startVoiceSession(shell.activeShellSessionId);
        }}
        onStop={() => {
          void shell.stopVoiceSession();
        }}
        onToggleMute={() => {
          if (effectiveStartDisabled) return;
          void shell.toggleVoiceMute();
        }}
      />
    </div>
  );
}

function DesktopShellHeader({
  activePage,
  onNavigate,
  broCount,
  nodeCount,
  accountLabel,
  accountId,
  onLogout,
  logoutPending,
}: {
  activePage: PageId;
  onNavigate: PageNavigator;
  broCount: number;
  nodeCount: number;
  accountLabel: string;
  accountId?: string | null;
  onLogout: () => void;
  logoutPending?: boolean;
}) {
  const nav = [
    { page: "Home" as const, count: broCount, icon: Home },
    { page: "Bros" as const, count: broCount, icon: Users },
    { page: "Nodes" as const, count: nodeCount, icon: Server },
    { page: "Settings" as const, count: null, icon: Settings },
  ];
  const initial = accountLabel.trim().charAt(0).toUpperCase() || "N";

  return (
    <header className="dt-header" data-testid="newbro-sidebar">
      <div className="dt-header-l">
        <button type="button" className="dt-header-brand border-0 bg-transparent p-0" onClick={() => onNavigate("Home")}>
          <div className="dt-header-brand-tile">
            <img src="/newbro.webp" alt="" draggable={false} />
          </div>
          <span className="dt-header-brand-name">newbro</span>
        </button>
        <span className="dt-header-sep" />
        <nav className="flex min-w-0 items-center gap-1" aria-label="Workspace">
          {nav.map(({ page, count, icon: Icon }) => (
            <button
              key={page}
              type="button"
              aria-label={page}
              onClick={() => onNavigate(page)}
              className={`dt-header-workspace ${activePage === page ? "border-[#ffb89e] bg-[#fff1ec] text-[#ff6a3d]" : ""}`}
            >
              <Icon className="h-3.5 w-3.5" strokeWidth={1.9} />
              <span className="dt-header-workspace-name">{page}</span>
              {count !== null ? <span className="dt-header-workspace-label">{count}</span> : null}
            </button>
          ))}
        </nav>
      </div>

      <div className="dt-header-r">
        <span className={`dt-header-pill ${nodeCount > 0 ? "dt-header-pill-ready" : "dt-header-pill-empty"}`}>
          <span className="dt-header-pill-dot" />
          <span className="dt-header-pill-label">{nodeCount > 0 ? "runtime ready" : "setup needed"}</span>
        </span>
        <span className="dt-header-icon-btn dt-header-search dt-header-static" aria-hidden="true">
          <Search className="h-3.5 w-3.5" strokeWidth={1.9} />
        </span>
        <div className="dt-header-account dt-header-static" aria-label="Signed in account">
          <span className="dt-header-account-avatar">{initial}</span>
          <span className="dt-header-account-name">{accountLabel}</span>
        </div>
        <button
          type="button"
          data-testid="sidebar-logout"
          className="dt-header-icon-btn"
          aria-label="Sign out"
          disabled={logoutPending}
          onClick={onLogout}
        >
          {logoutPending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <LogOut className="h-3.5 w-3.5" strokeWidth={1.9} />}
        </button>
        {accountId ? <span className="sr-only">{accountId}</span> : null}
      </div>
    </header>
  );
}

function ShellFrame({
  activePage,
  onNavigate,
  globalMessage,
  onGlobalMessageDismiss,
  broCount,
  nodeCount,
  accountLabel,
  accountId,
  onLogout,
  logoutPending,
  children,
}: {
  activePage: PageId;
  onNavigate: PageNavigator;
  globalMessage?: GlobalMessage | null;
  onGlobalMessageDismiss?: () => void;
  broCount: number;
  nodeCount: number;
  accountLabel: string;
  accountId?: string | null;
  onLogout: () => void;
  logoutPending?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="dt-frame min-h-dvh">
      <div className="dt-shell min-h-dvh">
        <DesktopShellHeader
          activePage={activePage}
          onNavigate={onNavigate}
          broCount={broCount}
          nodeCount={nodeCount}
          accountLabel={accountLabel}
          accountId={accountId}
          onLogout={onLogout}
          logoutPending={logoutPending}
        />
        <main data-testid="newbro-shell" className="dt-main">
          {children}
        </main>
        {globalMessage && onGlobalMessageDismiss ? (
          <GlobalMessageBanner message={globalMessage} onDismiss={onGlobalMessageDismiss} />
        ) : null}
      </div>
    </div>
  );
}

function FirstRunCreateSheet({
  sessionId,
  onClose,
  onCreated,
}: {
  sessionId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("atlas");
  const [command, setCommand] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = name.trim();
  const canCreate = trimmedName.length > 0 && !busy && !command;

  async function copyCommand(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function createAndConnect() {
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      const issue = await createExecutorNode(sessionId, {
        name: `${trimmedName} local node`,
        enabled_executors: ["codex"],
      });
      await createPersona(sessionId, {
        name: trimmedName,
        avatar: "bro",
        base_prompt: "Help turn voice instructions into clear executable drafts.",
        executor_node_id: issue.node.node_id,
      });
      const nextCommand = buildExecutorRunCommand(issue.node.node_id, issue.token, {
        enabledExecutors: issue.node.enabled_executors,
        acpxAgent: issue.node.acpx_agent,
      });
      setCommand(nextCommand);
      await copyCommand(nextCommand);
      await onCreated();
    } catch (createError: unknown) {
      setError(describeApiFailure(createError, "Could not create and connect this Bro."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nb-first-run-sheet-layer" role="dialog" aria-modal="true" aria-label="Create and connect a Bro">
      <div className="nb-first-run-sheet-frame ob-firsthome-sheet">
        <div className="ob-sheet-dim" onClick={onClose} aria-hidden="true" />
        <section className="ob-sheet">
          <div className="ob-sheet-handle" aria-hidden="true" />
          <header className="ob-sheet-head">
            <div className="ob-sheet-titles">
              <span className="ob-eyebrow ob-eyebrow-coral">NEW BRO</span>
              <h2 className="ob-sheet-h">Name it, then connect a node.</h2>
            </div>
            <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}>
              <X size={16} strokeWidth={2.2} />
            </button>
          </header>

          <div className="ob-sheet-body">
            <div className="ob-fieldset">
              <label className="ob-field">
                <span className="ob-field-eyebrow">NAME</span>
                <div className="ob-input ob-input-filled">
                  <span className="ob-input-prefix">@</span>
                  <input
                    type="text"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    disabled={Boolean(command) || busy}
                  />
                </div>
                <span className="ob-field-hint">One word, easy to say out loud. e.g. atlas, scout, forge, muse.</span>
              </label>
            </div>

            <div className="ob-fieldset">
              <span className="ob-field-eyebrow ob-fieldset-eyebrow">EXECUTOR</span>
              <div className="ob-exec-grid">
                <div className="ob-exec-card ob-exec-card-on">
                  <span className="ob-exec-check" aria-hidden="true">
                    <Check size={11} strokeWidth={2.8} />
                  </span>
                  <span className="ob-exec-name">Codex</span>
                  <span className="ob-exec-desc">Long-running agent · shell + browser</span>
                </div>
                <div className="ob-exec-card" aria-disabled="true">
                  <span className="ob-exec-name">Hermes</span>
                  <span className="ob-exec-desc">Headless · ops + scripts</span>
                </div>
              </div>
            </div>

            <div className="ob-fieldset">
              <div className="ob-fieldset-eyebrow-row">
                <span className="ob-field-eyebrow">CONNECT A NODE</span>
                <span className="ob-fieldset-eyebrow-meta">{command ? "ready" : "on demand"}</span>
              </div>
              <div className="ob-connect">
                <div className="ob-connect-cmd">
                  <span className="ob-connect-prompt">$</span>
                  <span className="ob-connect-line">
                    {command ? (
                      <>
                        {command.split("--token ")[0]}
                        <span className="ob-connect-tok">--token {command.split("--token ")[1] ?? ""}</span>
                      </>
                    ) : (
                      <>newbro executor run <span className="ob-connect-tok">--token pending</span></>
                    )}
                  </span>
                  <button
                    type="button"
                    className="ob-connect-copy"
                    aria-label="Copy command"
                    disabled={!command}
                    onClick={() => {
                      if (command) void copyCommand(command);
                    }}
                  >
                    {copied ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.9} />}
                  </button>
                </div>
                <div className="ob-connect-status">
                  <span className="ob-connect-spinner" aria-hidden="true">
                    <span /><span /><span />
                  </span>
                  <span className="ob-connect-status-text">
                    <strong>{command ? `Listening for ${trimmedName}...` : `Ready to create ${trimmedName || "a Bro"}...`}</strong>
                    <span>{command ? "Run that command on the machine where this Bro should work." : "Newbro will create a Bro and issue a local node command."}</span>
                  </span>
                  <span className="ob-connect-time">{copied ? "copied" : command ? "ready" : "new"}</span>
                </div>
              </div>
              {error ? <div className="nb-status-banner nb-status-banner-error">{error}</div> : null}
              {command ? (
                <div className="ob-connect-meta">
                  <span>Command is generated through the real node credential flow.</span>
                </div>
              ) : null}
            </div>
          </div>

          <footer className="ob-sheet-foot">
            <button
              type="button"
              className={`ob-cta ob-cta-block${busy ? " ob-cta-pending" : ""}`}
              disabled={!canCreate}
              onClick={() => { void createAndConnect(); }}
            >
              {busy ? <span className="ob-cta-spinner" aria-hidden="true" /> : null}
              <span>{busy ? "Preparing..." : command ? "Waiting for node..." : "Create and connect"}</span>
            </button>
          </footer>
        </section>
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
  const [firstRunSheetOpen, setFirstRunSheetOpen] = useState(false);

  return (
    <ShellFrame
      activePage="Home"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
      accountLabel={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
      accountId={shell.currentUser?.email ? shell.currentUser.user_id : null}
      onLogout={() => { void shell.logout(); }}
      logoutPending={shell.logoutPending}
    >

      {shell.hasLoadedShellSnapshot ? (
        <div className="dt-main-pad dt-home-pad">
          <ShellVoiceBar />
          <div className="dt-home-grid">
            <section className="dt-home-main">
              <header className="dt-page-head">
                <div>
                  <h1 className="dt-page-title">Workspace</h1>
                  <p className="dt-page-sub">
                    Your runtime crew, local executor nodes, and live work queue in one place.
                  </p>
                </div>
                {shell.runtimePersonas.length > 0 ? (
                  <div className="dt-page-actions">
                    <button type="button" className="dt-page-action dt-page-action-primary" onClick={() => onNavigate("Bros")}>
                      <Plus size={14} aria-hidden="true" />
                      <span>Manage Bros</span>
                    </button>
                  </div>
                ) : null}
              </header>

              {shell.runtimePersonas.length === 0 ? (
                <section className="ob-hero-card">
                  <div className="ob-hero-art">
                    <div className="ob-hero-mascot">
                      <img src="/newbro.webp" alt="" draggable={false} />
                    </div>
                    <span className="ob-hero-zzz" aria-hidden="true">
                      <i>z</i><i>z</i><i>z</i>
                    </span>
                  </div>
                  <div className="ob-hero-body">
                    <span className="ob-eyebrow ob-eyebrow-coral">Your crew · 0 Bros</span>
                    <h2 className="ob-hero-h">You don't have a bro yet.</h2>
                    <p className="ob-hero-sub">
                      Create a worker persona, bind it to a user-owned executor node, and it will appear here when Newbro can use it.
                    </p>
                    <div className="ob-hero-actions">
                      <button
                        type="button"
                        className="ob-cta ob-cta-block"
                        onClick={() => setFirstRunSheetOpen(true)}
                        disabled={!shell.activeShellSessionId}
                      >
                        <span>Create your first bro</span>
                      </button>
                    </div>
                  </div>
                </section>
              ) : (
                <section className="dt-home-section">
                  <div className="dt-home-section-head">
                    <div>
                      <span className="ob-eyebrow">Your crew · {shell.runtimePersonas.length}</span>
                      <p className="dt-home-section-sub">Live, queued, and resting Bros from the current Newbro session.</p>
                    </div>
                  </div>
                  <BrosPanel
                    bros={shell.bros}
                    sessionId={shell.activeShellSessionId}
                    onBroClick={(broId) => {
                      onBroNavigate?.(broId);
                    }}
                  />
                </section>
              )}
            </section>

            <aside className="dt-home-rail">
              <section className="dt-rail-block">
                <div className="dt-rail-block-head">
                  <span className="ob-eyebrow">Runtime</span>
                  <span className="dt-rail-block-sub">{shell.activeShellSessionId ? "connected" : "starting"}</span>
                </div>
                <ul className="dt-node-list">
                  <li className="dt-node-row">
                    <span className="dt-node-led dt-node-led-live" />
                    <span className="dt-node-body">
                      <span className="dt-node-name">{shell.runtimePersonas.length} Bros</span>
                      <span className="dt-node-meta">session</span>
                    </span>
                  </li>
                  <li className="dt-node-row">
                    <span className={shell.executorNodes.some((node) => node.connection_status === "connected") ? "dt-node-led dt-node-led-live" : "dt-node-led"} />
                    <span className="dt-node-body">
                      <span className="dt-node-name">{shell.executorNodes.length} Nodes</span>
                      <span className="dt-node-meta">{shell.executorNodes.filter((node) => node.connection_status === "connected").length} live</span>
                    </span>
                  </li>
                </ul>
              </section>
              <section className="dt-rail-block">
                <div className="dt-rail-block-head">
                  <span className="ob-eyebrow">Recent tasks</span>
                  <span className="dt-rail-block-sub">{shell.tasks.length}</span>
                </div>
                <div className="dt-recent-list">
                  {shell.tasks.slice(-4).reverse().map((task) => (
                    <article className="dt-recent" key={task.task_id}>
                      <span className="dt-recent-icon">›</span>
                      <span className="dt-recent-body">
                        <span className="dt-recent-title">{task.title}</span>
                        <span className="dt-recent-meta">{task.status}</span>
                      </span>
                    </article>
                  ))}
                  {shell.tasks.length === 0 ? <div className="dt-art-empty">No tasks yet.</div> : null}
                </div>
              </section>
            </aside>
          </div>
        </div>
      ) : shell.shellError ? (
        <ShellApiErrorPanel detail={shell.shellError} />
      ) : (
        <ShellLoadingPanel />
      )}
      {firstRunSheetOpen && shell.activeShellSessionId ? (
        <FirstRunCreateSheet
          sessionId={shell.activeShellSessionId}
          onClose={() => setFirstRunSheetOpen(false)}
          onCreated={shell.refreshShellSession}
        />
      ) : null}
    </ShellFrame>
  );
}

export function MobileWalkieShellPage() {
  const shell = useNewbroShell();
  const globalMessage = globalMessageFor(shell);

  if (shell.hasLoadedShellSnapshot) {
    return (
      <>
        <MobileWalkie
          bros={shell.bros}
          onSubmitMessage={shell.sendMessage}
          onStartVoice={shell.startMobileVoiceSession}
          onStopVoice={() => { void shell.stopMobileVoiceSession(); }}
          voicePhase={shell.voiceSession.phase}
        />
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

function BroSetupGate({
  bro,
  sessionId,
  nodeState,
  onBack,
  onReady,
  onGlobalError,
}: {
  bro: BroCardModel;
  sessionId: string | null;
  nodeState: BroNodeState;
  onBack: () => void;
  onReady: () => Promise<void>;
  onGlobalError: (message: string | null) => void;
}) {
  const [command, setCommand] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  async function copyCommand(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function setupLocalNode() {
    if (!sessionId || bro.source !== "runtime") {
      return;
    }
    setBusy(true);
    setError(null);
    onGlobalError(null);
    try {
      const issue = bro.executorNodeId
        ? await revealExecutorNodeConnectCommand(sessionId, bro.executorNodeId)
        : await createExecutorNode(sessionId, {
            name: `${bro.name} local node`,
            enabled_executors: ["codex"],
          });
      if (!bro.executorNodeId) {
        await updatePersona(sessionId, bro.id, {
          executor_node_id: issue.node.node_id,
        });
      }
      const nextCommand = buildExecutorRunCommand(issue.node.node_id, issue.token, {
        enabledExecutors: issue.node.enabled_executors,
        acpxAgent: issue.node.acpx_agent,
      });
      setCommand(nextCommand);
      await copyCommand(nextCommand);
      await onReady();
    } catch (setupError: unknown) {
      const detail = describeApiFailure(setupError, "Could not create and bind a local node.");
      setError(detail);
      onGlobalError(detail);
    } finally {
      setBusy(false);
    }
  }

  async function openBroDetail() {
    setOpening(true);
    setError(null);
    try {
      await onReady();
    } catch (refreshError: unknown) {
      const detail = describeApiFailure(refreshError, "Could not refresh this Bro after setup.");
      setError(detail);
      onGlobalError(detail);
    } finally {
      setOpening(false);
    }
  }

  return (
    <div className="dt-main-pad">
      <section className="dt-detail-main">
        <BroDetailHeader bro={bro} onBack={onBack} />
        <div className="space-y-5 sm:space-y-6">
          <section
            data-testid="bro-setup-gate"
            className="nb-setup-gate"
          >
            <div className="nb-setup-gate-head">
              <div className="nb-setup-gate-copy">
                <div className="command-label text-[#9ca3af]">Local executor required</div>
                <h2 className="mt-2 text-[24px] font-semibold tracking-normal text-[#111827]">
                  {nodeState.kind === "never_connected" ? "Waiting for first node connection" : "Set up this Bro before talking"}
                </h2>
                <p className="mt-2 text-[14px] leading-7 text-[#6b7280]">
                  {nodeState.kind === "never_connected"
                    ? `${nodeState.node.name} is bound to ${bro.name}, but it has not connected successfully yet. Run the local command and this page will unlock after the first connection appears in the session snapshot.`
                    : `Create a user-owned node, bind it to ${bro.name}, then run the command locally so this Bro has a place to execute work.`}
                </p>
              </div>
              <button
                type="button"
                data-testid="bro-setup-create-node"
                disabled={busy || !sessionId}
                onClick={() => { void setupLocalNode(); }}
                className="nb-page-primary-action inline-flex min-h-[42px] shrink-0 items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy ? <LoaderCircle className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Copy className="h-4 w-4" strokeWidth={2} />}
                {busy ? "Preparing..." : bro.executorNodeId ? "Copy command" : "Create node"}
              </button>
            </div>
            <div className="nb-setup-grid">
              <div className="ob-fieldset">
                <span className="ob-field-eyebrow ob-fieldset-eyebrow">EXECUTOR</span>
                <div className="ob-exec-grid">
                  <div className="ob-exec-card ob-exec-card-on">
                    <span className="ob-exec-name">Codex</span>
                    <span className="ob-exec-desc">Long-running agent · shell + browser</span>
                    <span className="ob-exec-check" aria-hidden="true">
                      <Check size={11} strokeWidth={2.8} />
                    </span>
                  </div>
                  <div className="ob-exec-card" aria-disabled="true">
                    <span className="ob-exec-name">Hermes</span>
                    <span className="ob-exec-desc">Headless · ops + scripts</span>
                  </div>
                </div>
              </div>
              <div className="ob-fieldset">
                <div className="ob-fieldset-eyebrow-row">
                  <span className="ob-field-eyebrow">CONNECT A NODE</span>
                  <span className="ob-fieldset-eyebrow-meta">{command ? "ready" : "on demand"}</span>
                </div>
                <div className={`ob-connect${!command ? " nb-setup-connect-muted" : ""}`}>
                  <div className="ob-connect-cmd">
                    <span className="ob-connect-prompt">$</span>
                    <span className="ob-connect-line">
                      {command ? (
                        <>
                          {command.split("--token ")[0]}
                          <span className="ob-connect-tok">--token {command.split("--token ")[1] ?? ""}</span>
                        </>
                      ) : (
                        <>newbro executor run <span className="ob-connect-tok">--token pending</span></>
                      )}
                    </span>
                    <button
                      type="button"
                      className="ob-connect-copy"
                      aria-label="Copy command"
                      disabled={!command}
                      onClick={() => {
                        if (command) void copyCommand(command);
                      }}
                    >
                      {copied ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.9} />}
                    </button>
                  </div>
                  <div className="ob-connect-status">
                    <span className="ob-connect-spinner" aria-hidden="true">
                      <span /><span /><span />
                    </span>
                    <span className="ob-connect-status-text">
                      <strong>{command ? `Listening for ${bro.name}...` : `Ready to issue a command for ${bro.name}.`}</strong>
                      <span>
                        {command
                          ? `Run that command on the machine where ${bro.name} should work.`
                          : "Create or reveal the node command through the real credential flow."}
                      </span>
                    </span>
                    <span className="ob-connect-time">{copied ? "copied" : command ? "ready" : "new"}</span>
                  </div>
                </div>
              </div>
            </div>
            {error ? (
              <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-600">
                {error}
              </div>
            ) : null}
            {command ? (
              <div className="mt-5 space-y-4">
                <div className="flex items-center gap-2 text-[13px] font-semibold text-[#111827]">
                  <Check className="h-4 w-4 text-[#059669]" strokeWidth={2} />
                  Local command {copied ? "copied" : "ready"}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-full border border-[#e5e7eb] bg-white px-4 py-2 text-[13px] font-semibold text-[#6b7280] transition hover:bg-[#fafafa] hover:text-[#111827]"
                    onClick={() => { void copyCommand(command); }}
                  >
                    Copy command
                  </button>
                  <button
                    type="button"
                    data-testid="bro-setup-open-detail"
                    disabled={opening}
                    className="nb-page-primary-action inline-flex min-h-[38px] items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={() => { void openBroDetail(); }}
                  >
                    {opening ? "Checking..." : "Check connection"}
                  </button>
                </div>
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] leading-6 text-amber-800">
                  Waiting for this node to connect successfully once. Normal Bro Detail stays locked until Newbro sees that first connection.
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </section>
    </div>
  );
}

function NodeDisconnectedWarning({
  bro,
  node,
  sessionId,
  onGlobalError,
}: {
  bro: BroCardModel;
  node: ExecutorNodeRecord;
  sessionId: string | null;
  onGlobalError: (message: string | null) => void;
}) {
  const [command, setCommand] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function copyCommand(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  async function revealCommand() {
    if (!sessionId || bro.source !== "runtime") return;
    setBusy(true);
    setError(null);
    onGlobalError(null);
    try {
      const issue = await revealExecutorNodeConnectCommand(sessionId, node.node_id);
      const nextCommand = buildExecutorRunCommand(issue.node.node_id, issue.token, {
        enabledExecutors: issue.node.enabled_executors,
        acpxAgent: issue.node.acpx_agent,
      });
      setCommand(nextCommand);
      await copyCommand(nextCommand);
    } catch (revealError: unknown) {
      const detail = describeApiFailure(revealError, "Could not reveal the local node command.");
      setError(detail);
      onGlobalError(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="bro-node-disconnected-warning"
      className="mx-4 mt-4 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-4 text-amber-900 md:mx-6 xl:mx-8"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-normal text-amber-700">Local node offline</div>
          <div className="mt-1 text-[14px] leading-6">
            {disconnectedNodeWarning(node)}
          </div>
        </div>
        <button
          type="button"
          data-testid="bro-node-copy-command"
          disabled={busy || !sessionId}
          className="rounded-full border border-amber-200 bg-white px-4 py-2 text-[13px] font-semibold text-amber-800 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={() => { void revealCommand(); }}
        >
          {busy ? "Preparing..." : copied ? "Copied" : "Copy command"}
        </button>
      </div>
      {error ? <div className="mt-3 text-[13px] leading-6 text-red-600">{error}</div> : null}
      {command ? (
        <pre className="command-field mt-3 max-h-[160px] overflow-auto whitespace-pre-wrap break-all bg-white/80 px-4 py-3 text-[12.5px] leading-6 text-[#374151]">
          {command}
        </pre>
      ) : null}
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
  const nodeState = deriveBroNodeState(bro, shell.executorNodes);
  const setupRequired = bro?.source === "runtime" && nodeStateRequiresSetup(nodeState);
  const voiceBlocked = bro?.source === "runtime" && !nodeStateAllowsVoice(nodeState);
  const voiceBlockReason = nodeState.kind === "usable_disconnected"
    ? disconnectedNodeWarning(nodeState.node)
    : null;
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
    if (!shell.hasLoadedShellSnapshot || !shell.activeShellSessionId || !bro || setupRequired) {
      return undefined;
    }
    const sessionId = shell.activeShellSessionId;
    void setVoiceTarget(sessionId, bro.id).catch((error: unknown) => {
      shell.setShellError(describeApiFailure(error, "Could not bind voice to this Bro."));
    });
    return () => {
      void clearVoiceTarget(sessionId).catch(() => {});
    };
  }, [shell.hasLoadedShellSnapshot, shell.activeShellSessionId, bro?.id, setupRequired]);

  useEffect(() => {
    if (voiceBlocked && shell.voiceSession.phase === "connected" && !shell.voiceSession.isMicMuted) {
      void shell.toggleVoiceMute();
    }
  }, [voiceBlocked, shell.voiceSession.phase, shell.voiceSession.isMicMuted]);

  return (
    <ShellFrame
      activePage="Home"
      onNavigate={onNavigate}
      globalMessage={globalMessageFor(shell)}
      onGlobalMessageDismiss={shell.clearGlobalMessage}
      broCount={shell.runtimePersonas.length}
      nodeCount={shell.executorNodes.length}
      accountLabel={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
      accountId={shell.currentUser?.email ? shell.currentUser.user_id : null}
      onLogout={() => { void shell.logout(); }}
      logoutPending={shell.logoutPending}
    >
      {shell.hasLoadedShellSnapshot ? (
        bro ? (
          setupRequired ? (
            <BroSetupGate
              bro={bro}
              sessionId={shell.activeShellSessionId}
              nodeState={nodeState}
              onBack={() => onNavigate("Home")}
              onReady={shell.refreshShellSession}
              onGlobalError={shell.setShellError}
            />
          ) : (
            <div className="dt-main-pad">
              <ShellVoiceBar startDisabled={voiceBlocked} blockReason={voiceBlockReason} />
              {nodeState.kind === "usable_disconnected" ? (
                <NodeDisconnectedWarning
                  bro={bro}
                  node={nodeState.node}
                  sessionId={shell.activeShellSessionId}
                  onGlobalError={shell.setShellError}
                />
              ) : null}
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
                voiceInputDisabled={voiceBlocked}
                voiceInputDisabledReason={voiceBlockReason}
                onBack={() => onNavigate("Home")}
                onGlobalError={shell.setShellError}
              />
            </div>
          )
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="glass-panel max-w-[520px] rounded-[30px] border border-white/75 px-6 py-6 text-center">
              <div className="serif-flow text-[32px] tracking-normal">Bro not found</div>
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
      accountLabel={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
      accountId={shell.currentUser?.email ? shell.currentUser.user_id : null}
      onLogout={() => { void shell.logout(); }}
      logoutPending={shell.logoutPending}
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
      accountLabel={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
      accountId={shell.currentUser?.email ? shell.currentUser.user_id : null}
      onLogout={() => { void shell.logout(); }}
      logoutPending={shell.logoutPending}
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
      accountLabel={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
      accountId={shell.currentUser?.email ? shell.currentUser.user_id : null}
      onLogout={() => { void shell.logout(); }}
      logoutPending={shell.logoutPending}
    >
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="text-[14px] text-neutral-400">Settings coming soon.</div>
      </div>
    </ShellFrame>
  );
}
