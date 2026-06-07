import React, { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent } from "react";
import { ArrowUp, Check, ChevronLeft, Download, FileText, GitBranch, Layers, LogOut, MessageSquare, Mic, Pencil, Plus, Radio, Settings, WifiOff, X } from "lucide-react";
import {
  buildExecutorConnectCommands,
  claimDevice,
  clearDraft,
  clearVoiceTarget,
  createExecutorNode,
  createPersona,
  deletePersona,
  listExecutorNodes,
  revealExecutorNodeConnectCommand,
  setVoiceTarget,
  submitExecutorAudioInstruction,
  submitExecutorTextInstruction,
  updatePersona,
  type ExecutorConnectCommands,
} from "./lib/session-client";
import { useThreadSelection } from "./lib/useThreadSelection";
import { buildBroCardModels, buildBroThreadRecords, buildReasoningStepsForNativeTurn, buildReasoningStepsForTurn, type ReasoningStep } from "./components/newbro/adapters";
import { BroAvatar, avatarTypeToCharacter } from "./components/newbro/BroAvatar";
import { DevicePairingForm } from "./components/newbro/DevicePairingForm";
import { MarkdownText } from "./components/ui/markdown-text";
import { useNewbroShell } from "./NewbroShell";
import { deriveLiveTurnState } from "./lib/reasoningPhase";
import { splitLiveSteps } from "./lib/splitLiveSteps";
import { LiveTurnBubble } from "./LiveTurnBubble";
import { timelineRowKey } from "./lib/timelineRowKey";
import type { BroThread, BroTimelineMessage, BroTimelineTask, BroTimelineTurn, ExecutionRun, ExecutorNodeRecord, InteractionRequest, Persona, Task } from "./types";
import type { BroCardModel, BroTaskRecord, BroThreadRecord } from "./components/newbro/types";

const APP_DOWNLOAD_URL = "https://github.com/AgoraIO-Community/Newbro/releases/latest";

type RuntimePage = "home" | "detail";
type HomeBroState = "working" | "idle" | "offline";

type HomeRecentItem = {
  id: string;
  broId: string;
  threadId: string;
  title: string;
  bro: string;
  when: string;
};

type AudioTurnStatus = "recording" | "sending" | "sent" | "failed";
type TextTurnStatus = "sending" | "sent" | "failed";

type AudioTurn = {
  id: string;
  audioInstructionId?: string;
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
  planMode?: boolean;
  createdAt?: string;
  timestampLabel?: string;
  error?: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  id: string;
  planMode?: boolean;
  createdAt?: string;
};

const THREAD_LIST_PAGE_SIZE = 15;

type WorkspaceOption = {
  id: string;
  name: string;
};

function directExecutorMetric(stage: string, details: Record<string, unknown>): void {
  const payload = {
    stage,
    at: new Date().toISOString(),
    ...details,
  };
  window.dispatchEvent(new CustomEvent("newbro:direct-executor-metric", { detail: payload }));
  if (import.meta.env.MODE !== "test") {
    // eslint-disable-next-line no-console
    console.info("[newbro:direct-executor]", payload);
  }
}

function turnMatchesThread<T extends { threadId?: string | null }>(turn: T, threadId: string | null): boolean {
  return threadId === null ? !turn.threadId : turn.threadId === threadId;
}

function timelineTurnMatchesThread(turn: BroTimelineTurn, broId: string, threadId: string | null): boolean {
  return turn.persona_id === broId && threadId !== null && turn.thread_id === threadId;
}

function workspaceNameFromId(workspaceId: string): string {
  const normalized = workspaceId.trim().replace(/[\\/]+$/, "");
  const tail = normalized.replace(/\\/g, "/").split("/").filter(Boolean).pop();
  return tail || normalized || workspaceId;
}

function buildWorkspaceOptions(threads: BroThreadRecord[]): WorkspaceOption[] {
  const options = new Map<string, WorkspaceOption>();
  for (const thread of threads) {
    if (!thread.workspaceId) continue;
    if (options.has(thread.workspaceId)) continue;
    options.set(thread.workspaceId, {
      id: thread.workspaceId,
      name: thread.workspaceName?.trim() || workspaceNameFromId(thread.workspaceId),
    });
  }
  return [...options.values()].sort((left, right) => left.name.localeCompare(right.name));
}

function WorkspacePickerDialog({
  open,
  broName,
  workspaceOptions,
  onSelectWorkspace,
  onClose,
}: {
  open: boolean;
  broName: string;
  workspaceOptions: WorkspaceOption[];
  onSelectWorkspace: (workspaceId: string) => void;
  onClose: () => void;
}) {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setSelectedWorkspaceId(null);
      return undefined;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  function confirmSelection() {
    if (!selectedWorkspaceId) return;
    onSelectWorkspace(selectedWorkspaceId);
  }

  return (
    <div
      className="nb-first-run-sheet-layer nb-workspace-dialog-layer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="nb-workspace-dialog-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="nb-first-run-sheet-frame ob-firsthome-sheet nb-workspace-dialog-frame" onMouseDown={(event) => event.stopPropagation()}>
        <div className="ob-sheet-dim" onClick={onClose} aria-hidden="true" />
        <section className="ob-sheet nb-workspace-dialog">
          <div className="ob-sheet-handle" aria-hidden="true" />
          <header className="ob-sheet-head">
            <div className="ob-sheet-titles">
              <span className="ob-eyebrow ob-eyebrow-coral">WORKSPACE</span>
              <h2 id="nb-workspace-dialog-title" className="ob-sheet-h">Choose a workspace for {broName}.</h2>
            </div>
            <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}>
              <X size={16} strokeWidth={2.2} />
            </button>
          </header>
          <div className="ob-sheet-body">
            <div className="ob-fieldset">
              <div className="ob-fieldset-eyebrow-row">
                <span className="ob-field-eyebrow">AVAILABLE WORKSPACES</span>
                <span className="ob-fieldset-eyebrow-meta">{workspaceOptions.length} known</span>
              </div>
              <div className="nb-workspace-scroll">
                <div className="ob-exec-grid nb-workspace-list">
                  {workspaceOptions.map((workspace) => (
                    <button
                      key={workspace.id}
                      type="button"
                      className={`ob-exec-card nb-workspace-card${selectedWorkspaceId === workspace.id ? " ob-exec-card-on" : ""}`}
                      aria-label={`${workspace.name} workspace ${workspace.id}`}
                      aria-pressed={selectedWorkspaceId === workspace.id}
                      onClick={() => setSelectedWorkspaceId(workspace.id)}
                    >
                      <span className="ob-exec-name nb-workspace-name">{workspace.name}</span>
                      <span className="ob-exec-desc nb-workspace-path">{workspace.id}</span>
                      {selectedWorkspaceId === workspace.id ? (
                        <span className="ob-exec-check" aria-hidden="true"><Check size={11} strokeWidth={2.8} /></span>
                      ) : null}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <footer className="ob-sheet-foot">
            <span className="dt-modal-foot-status nb-create-connect-foot-status nb-workspace-foot-status">
              <span className="dt-modal-foot-dot" />
              New Codex threads start inside the selected workspace
            </span>
            <button
              type="button"
              className={`ob-cta nb-workspace-confirm${!selectedWorkspaceId ? " ob-cta-pending" : ""}`}
              disabled={!selectedWorkspaceId}
              onClick={confirmSelection}
            >
              OK
            </button>
          </footer>
        </section>
      </div>
    </div>
  );
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

function timelineTimestamp(value: string | undefined): number {
  if (!value) return Number.NEGATIVE_INFINITY;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function turnUserText(turn: BroTimelineTurn): string {
  if (!turn.user) return "";
  return (turn.user.kind === "audio" ? turn.user.transcript : turn.user.text)?.trim() ?? "";
}

function optimisticTextTurnToTimeline(turn: TextTurn): BroTimelineTurn {
  return {
    turn_id: `optimistic:${turn.id}`,
    thread_id: turn.threadId ?? "",
    persona_id: turn.broId,
    executor_id: "codex",
    owner: "newbro",
    client_request_id: turn.id,
    executor_thread_id: null,
    executor_turn_id: null,
    input_modality: "text",
    user: {
      message_id: `optimistic:${turn.id}:user`,
      role: "user",
      kind: "text",
      text: turn.text,
      transcript: null,
      audio_id: null,
      duration_ms: null,
      created_at: turn.createdAt ?? null,
      updated_at: turn.createdAt ?? null,
      status: turn.status,
      metadata: turn.planMode ? { plan_mode: true } : {},
    },
    assistant: null,
    task: null,
    status: turn.status === "failed" ? "failed" : turn.status === "sent" ? "running" : "pending",
    created_at: turn.createdAt ?? null,
    updated_at: turn.createdAt ?? null,
    metadata: { optimistic: true, ...(turn.planMode ? { plan_mode: true } : {}) },
  };
}

function optimisticAudioTurnToTimeline(turn: AudioTurn): BroTimelineTurn {
  return {
    turn_id: `optimistic:${turn.id}`,
    thread_id: turn.threadId ?? "",
    persona_id: turn.broId,
    executor_id: "codex",
    owner: "newbro",
    client_request_id: turn.id,
    executor_thread_id: null,
    executor_turn_id: null,
    input_modality: "audio",
    user: {
      message_id: `optimistic:${turn.id}:user`,
      role: "user",
      kind: "audio",
      text: null,
      transcript: turn.transcript ?? null,
      audio_id: turn.audioInstructionId ?? turn.id,
      duration_ms: turn.durationMs,
      created_at: turn.createdAt ?? null,
      updated_at: turn.createdAt ?? null,
      status: turn.status,
      metadata: {},
    },
    assistant: null,
    task: null,
    status: turn.status === "failed" ? "failed" : turn.status === "sent" ? "running" : "pending",
    created_at: turn.createdAt ?? null,
    updated_at: turn.createdAt ?? null,
    metadata: { optimistic: true },
  };
}

function buildTimelineTurns({
  timelineTurns,
  textTurns,
  audioTurns,
  broId,
  threadId,
}: {
  timelineTurns: BroTimelineTurn[];
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  broId: string;
  threadId: string | null;
}): BroTimelineTurn[] {
  const canonical = timelineTurns.filter((turn) => timelineTurnMatchesThread(turn, broId, threadId));
  const canonicalClientIds = new Set(
    canonical.map((turn) => turn.client_request_id).filter((value): value is string => Boolean(value)),
  );
  const optimistic = [
    ...textTurns.filter((turn) => !canonicalClientIds.has(turn.id)).map(optimisticTextTurnToTimeline),
    ...audioTurns.filter((turn) => !canonicalClientIds.has(turn.id)).map(optimisticAudioTurnToTimeline),
  ];
  const sortedOptimistic = optimistic.sort((left, right) => {
    const timeDelta = timelineTimestamp(left.created_at ?? left.updated_at ?? undefined)
      - timelineTimestamp(right.created_at ?? right.updated_at ?? undefined);
    if (timeDelta !== 0) return timeDelta;
    return left.turn_id.localeCompare(right.turn_id);
  });
  return [...canonical, ...sortedOptimistic];
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
      {turn.planMode ? (
        <span className={`${prefix}-plantag`} aria-label="Sent in plan mode">
          <GitBranch size={12} strokeWidth={2.2} aria-hidden="true" />
          Plan mode
        </span>
      ) : null}
      <div className={`${prefix}-bubble ${prefix}-bubble-you${turn.planMode ? ` ${prefix}-bubble-plan` : ""}${turn.status === "failed" ? " ob-bubble-failed" : ""}`}>
        <MarkdownText>{turn.text}</MarkdownText>
      </div>
      <div className={metaClass}>
        <MessageMeta
          label={meta}
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

const TASK_RECORD_TITLE_MAX_CHARS = 60;

function shortenTaskRecordTitle(value: string): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (collapsed.length <= TASK_RECORD_TITLE_MAX_CHARS) return collapsed;
  return collapsed.slice(0, TASK_RECORD_TITLE_MAX_CHARS - 1).trimEnd() + "…";
}

function TaskRecordCard({ bro, record, mobile = false }: { bro: BroCardModel; record: BroTaskRecord; mobile?: boolean }) {
  const active = taskRecordIsActive(record);
  const prefix = mobile ? "thr" : "dt";
  const statusClass = mobile ? "thr-status" : "dt-status";
  const doneClass = mobile ? "thr-status-done" : "dt-status-done";
  const spinClass = mobile ? "thr-status-spin" : "dt-status-spin";
  const doneDotClass = mobile ? "thr-status-done-dot" : "dt-status-done-dot";
  const titleClass = mobile ? "thr-status-title" : "dt-status-title";
  const barClass = mobile ? "thr-status-bar" : "dt-status-bar";
  const footClass = mobile ? "thr-status-foot" : "dt-status-foot";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";
  const bodyText = record.summary || record.description;
  const fullTitle = record.title.trim();
  const title = shortenTaskRecordTitle(fullTitle);
  return (
    <div className={`${prefix}-turn ${prefix}-turn-bro`}>
      <div className={`${statusClass}${active ? "" : ` ${doneClass}`}`}>
        {title ? (
          <div className={`${statusClass}-head`}>
            {active ? <span className={spinClass} /> : <span className={doneDotClass} />}
            <span className={titleClass} title={fullTitle !== title ? fullTitle : undefined}>{title}</span>
          </div>
        ) : null}
        <div className={barClass}><i style={{ width: `${Math.max(8, Math.min(100, Math.round(record.progress)))}%` }} /></div>
        <div className={`${footClass} ${prefix}-task-body`}>
          {record.plan ? <TaskPlanView plan={record.plan} prefix={prefix} /> : null}
          {bodyText ? (
            <div className={`${prefix}-task-narration`}>
              <MarkdownText>{bodyText}</MarkdownText>
            </div>
          ) : null}
        </div>
      </div>
      <div className={metaClass}>
        <MessageMeta label={record.statusLabel} />
      </div>
    </div>
  );
}

function TaskPlanView({ plan, prefix }: { plan: NonNullable<BroTaskRecord["plan"]>; prefix: "dt" | "thr" }) {
  const totalSteps = plan.steps.length;
  const completedSteps = plan.steps.filter((step) => step.status === "completed").length;
  const hasText = Boolean(plan.explanation || plan.text);
  return (
    <section className={`${prefix}-task-plan-card`}>
      <div className={`${prefix}-task-chip ${prefix}-task-chip-plan`}>
        <span className={`${prefix}-task-chip-label`}>Plan</span>
        {totalSteps > 0 ? (
          <span className={`${prefix}-task-chip-progress`}>{completedSteps} / {totalSteps}</span>
        ) : null}
      </div>
      {plan.explanation ? (
        <div className={`${prefix}-task-plan-explanation`}>
          <MarkdownText>{plan.explanation}</MarkdownText>
        </div>
      ) : null}
      {plan.steps.length > 0 ? (
        <ol className={`${prefix}-task-plan`}>
          {plan.steps.map((step, index) => (
            <li key={`${step.status}-${index}`} className={`${prefix}-task-plan-item ${prefix}-task-plan-item-${step.status}`}>
              <span className={`${prefix}-task-plan-status ${prefix}-task-plan-status-${step.status}`} aria-hidden="true" />
              <span className={`${prefix}-task-plan-step`}>{step.step}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {plan.text && plan.text !== plan.explanation ? (
        <div className={`${prefix}-task-plan-explanation`}>
          <MarkdownText>{plan.text}</MarkdownText>
        </div>
      ) : null}
      {!hasText && plan.steps.length === 0 ? (
        <div className={`${prefix}-task-plan-empty`}>Plan pending.</div>
      ) : null}
    </section>
  );
}

type PlanProposalOption = {
  id: string;
  label: string;
  description: string;
  letter?: string;
};

type PlanProposalQuestion = {
  questionId: string;
  header: string;
  summary: string;
  options: PlanProposalOption[];
};

const PLAN_APPROVAL_VISIBLE_TEXT = "Implement it";

function normalizePlanProposalOptions(value: unknown): PlanProposalOption[] {
  return Array.isArray(value)
    ? value.flatMap((option, index) => {
        if (!option || typeof option !== "object" || Array.isArray(option)) return [];
        const item = option as Record<string, unknown>;
        const label = typeof item.label === "string" ? item.label.trim() : "";
        if (!label) return [];
        const id = typeof item.id === "string" && item.id.trim() ? item.id.trim() : label;
        return [{
          id,
          label,
          description: typeof item.description === "string" ? item.description.trim() : "",
          letter: typeof item.letter === "string" && item.letter.trim() ? item.letter.trim() : String.fromCharCode(65 + index),
        }];
      })
    : [];
}

function planProposalDetails(request: InteractionRequest): {
  summary: string;
  options: PlanProposalOption[];
  questions: PlanProposalQuestion[];
} {
  const proposal = request.details?.proposal;
  if (!proposal || typeof proposal !== "object" || Array.isArray(proposal)) {
    return { summary: request.prompt, options: [], questions: [] };
  }
  const raw = proposal as Record<string, unknown>;
  const summary = typeof raw.summary === "string" && raw.summary.trim() ? raw.summary.trim() : request.prompt;
  const options = normalizePlanProposalOptions(raw.options);
  const questions = Array.isArray(raw.questions)
    ? raw.questions.flatMap((question, index) => {
        if (!question || typeof question !== "object" || Array.isArray(question)) return [];
        const item = question as Record<string, unknown>;
        const questionId = typeof item.question_id === "string" && item.question_id.trim()
          ? item.question_id.trim()
          : `question_${index + 1}`;
        const questionSummary = typeof item.summary === "string" && item.summary.trim()
          ? item.summary.trim()
          : summary;
        const header = typeof item.header === "string" && item.header.trim()
          ? item.header.trim()
          : questionSummary;
        return [{
          questionId,
          header,
          summary: questionSummary,
          options: normalizePlanProposalOptions(item.options),
        }];
      })
    : [];
  return { summary, options, questions };
}

function optionAnswerText(option: PlanProposalOption | null): string | undefined {
  if (!option) return undefined;
  return option.label;
}

function PlanProposalCard({
  request,
  mobile = false,
  broId,
  threadId,
  onTextTurn,
}: {
  request: InteractionRequest;
  mobile?: boolean;
  broId?: string;
  threadId?: string | null;
  onTextTurn?: (turn: TextTurn) => void;
}) {
  const shell = useNewbroShell();
  const prefix = mobile ? "thr" : "dt";
  const { summary, options, questions } = planProposalDetails(request);
  const multiQuestions = questions.length > 1 ? questions : [];
  const selectedFromRequest = typeof request.details?.selected_option_id === "string" ? request.details.selected_option_id : null;
  const proposal = request.details?.proposal;
  const isFinalCodexPlan = Boolean(proposal && typeof proposal === "object" && !Array.isArray(proposal) && "codex_plan" in proposal);
  const isSingleOptionFinalApprove = isFinalCodexPlan
    && multiQuestions.length === 0
    && options.length === 1
    && request.available_actions.includes("approve");
  const codexPlan = isFinalCodexPlan && proposal && typeof proposal === "object" && !Array.isArray(proposal)
    ? timelinePlan((proposal as Record<string, unknown>).codex_plan)
    : undefined;
  const [selectedId, setSelectedId] = useState<string | null>(selectedFromRequest);
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, string>>({});
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(multiQuestions[0]?.questionId ?? null);
  const [resolving, setResolving] = useState(false);
  const selected = options.find((option) => option.id === selectedId) ?? null;
  const effectiveSelected = isSingleOptionFinalApprove ? options[0] : selected;
  const activeQuestion = multiQuestions.find((question) => question.questionId === activeQuestionId) ?? multiQuestions[0] ?? null;
  const allQuestionsAnswered = multiQuestions.length > 0
    && multiQuestions.every((question) => Boolean(selectedAnswers[question.questionId]));
  const pending = request.status === "pending";
  function selectQuestionOption(question: PlanProposalQuestion, option: PlanProposalOption) {
    if (resolving) return;
    const nextAnswers = { ...selectedAnswers, [question.questionId]: option.label };
    setSelectedAnswers(nextAnswers);
    const nextQuestion = multiQuestions.find((candidate) => !nextAnswers[candidate.questionId]);
    if (nextQuestion) {
      setActiveQuestionId(nextQuestion.questionId);
    }
  }
  function compactAnswersSummary(): string {
    return multiQuestions
      .map((question) => `${question.header}: ${selectedAnswers[question.questionId] ?? ""}`)
      .filter((part) => !part.endsWith(": "))
      .join("; ");
  }
  async function resolve(action: "approve" | "deny") {
    if (!pending || resolving) return;
    if (action === "approve" && multiQuestions.length > 0 && !allQuestionsAnswered) return;
    if (action === "approve" && !isSingleOptionFinalApprove && multiQuestions.length === 0 && !selected) return;
    const answerText = action === "approve"
      ? (multiQuestions.length > 0 ? compactAnswersSummary() : optionAnswerText(effectiveSelected) ?? PLAN_APPROVAL_VISIBLE_TEXT)
      : "Keep planning. Refine the proposal instead of acting yet.";
    const visibleText = action === "approve"
      ? (isSingleOptionFinalApprove ? PLAN_APPROVAL_VISIBLE_TEXT : answerText)
      : null;
    const optimisticBroId = broId ?? interactionRequestDetailText(request, "persona_id");
    const optimisticThreadId = threadId ?? interactionRequestDetailText(request, "target_thread_id");
    const clientRequestId = action === "approve"
      ? `plan-approval-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      : null;
    const createdAt = new Date().toISOString();
    if (action === "approve" && clientRequestId && optimisticBroId) {
      onTextTurn?.({
        id: clientRequestId,
        broId: optimisticBroId,
        threadId: optimisticThreadId,
        text: visibleText ?? PLAN_APPROVAL_VISIBLE_TEXT,
        status: "sending",
        createdAt,
      });
    }
    setResolving(true);
    try {
      await shell.resolveInteractionRequest(request.request_id, {
        action,
        answer_text: answerText,
        ...(multiQuestions.length > 0 && action === "approve" ? {
          answers: Object.fromEntries(
            multiQuestions.map((question) => [question.questionId, [selectedAnswers[question.questionId]]]),
          ),
        } : {}),
        ...(multiQuestions.length === 0 && effectiveSelected?.id ? { option_id: effectiveSelected.id } : {}),
        ...(clientRequestId ? {
          client_request_id: clientRequestId,
          user_visible_text: visibleText ?? PLAN_APPROVAL_VISIBLE_TEXT,
        } : {}),
      });
      if (action === "approve" && clientRequestId && optimisticBroId) {
        onTextTurn?.({
          id: clientRequestId,
          broId: optimisticBroId,
          threadId: optimisticThreadId,
          text: visibleText ?? PLAN_APPROVAL_VISIBLE_TEXT,
          status: "sent",
          createdAt,
        });
      }
    } catch (error: unknown) {
      const message = describeError(error, "Plan approval could not be sent.");
      if (action === "approve" && clientRequestId && optimisticBroId) {
        onTextTurn?.({
          id: clientRequestId,
          broId: optimisticBroId,
          threadId: optimisticThreadId,
          text: visibleText ?? PLAN_APPROVAL_VISIBLE_TEXT,
          status: "failed",
          createdAt,
          error: message,
        });
      }
      shell.setShellError(message);
    } finally {
      setResolving(false);
    }
  }
  if (!pending) return null;
  return (
    <div className={`${prefix}-turn ${prefix}-turn-bro ${prefix}-turn-plan`}>
      <div className={mobile ? "plan-prop" : "dt-planprop"}>
        <div className={mobile ? "plan-prop-head" : "dt-planprop-head"}>
          <span className={mobile ? "plan-prop-glyph" : "dt-planprop-glyph"} aria-hidden="true">
            <GitBranch size={14} strokeWidth={2.2} />
          </span>
          <span className={mobile ? "plan-prop-title" : "dt-planprop-title"}>Proposed plans</span>
          <span className={mobile ? "plan-prop-tag" : "dt-planprop-tag"}>
            {isSingleOptionFinalApprove
              ? "REVIEW"
              : options.length > 0 ? `${options.length} OPTIONS` : "REVIEW"}
          </span>
        </div>
        {codexPlan ? (
          <TaskPlanView plan={codexPlan} prefix={prefix} />
        ) : (
          <p className={mobile ? "plan-prop-summary" : "dt-planprop-summary"}>{summary}</p>
        )}
        {multiQuestions.length > 0 && activeQuestion ? (
          <>
            <div className={mobile ? "plan-tabs" : "dt-plantabs"} role="tablist" aria-label="Plan questions">
              {multiQuestions.map((question, index) => {
                const on = question.questionId === activeQuestion.questionId;
                const answered = Boolean(selectedAnswers[question.questionId]);
                return (
                  <button
                    key={question.questionId}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    className={`${mobile ? "plan-tab" : "dt-plantab"}${on ? ` ${mobile ? "plan-tab-on" : "dt-plantab-on"}` : ""}${answered ? ` ${mobile ? "plan-tab-done" : "dt-plantab-done"}` : ""}`}
                    onClick={() => setActiveQuestionId(question.questionId)}
                    disabled={resolving}
                  >
                    {question.header || `Question ${index + 1}`}
                  </button>
                );
              })}
            </div>
            <p className={mobile ? "plan-question" : "dt-planquestion"}>{activeQuestion.summary}</p>
            <div className={mobile ? "plan-opts" : "dt-planopts"} role="radiogroup" aria-label={activeQuestion.header}>
              {activeQuestion.options.map((option) => {
                const on = selectedAnswers[activeQuestion.questionId] === option.label;
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className={`${mobile ? "plan-opt" : "dt-planopt"}${on ? ` ${mobile ? "plan-opt-on" : "dt-planopt-on"}` : ""}`}
                    onClick={() => selectQuestionOption(activeQuestion, option)}
                    disabled={resolving}
                  >
                    <span className={mobile ? "plan-opt-radio" : "dt-planopt-radio"} aria-hidden="true" />
                    <span className={mobile ? "plan-opt-body" : "dt-planopt-body"}>
                      <span className={mobile ? "plan-opt-top" : "dt-planopt-top"}>
                        <span className={mobile ? "plan-opt-letter" : "dt-planopt-letter"}>{option.letter}</span>
                        <span className={mobile ? "plan-opt-label" : "dt-planopt-label"}>{option.label}</span>
                      </span>
                      {option.description ? <span className={mobile ? "plan-opt-text" : "dt-planopt-text"}>{option.description}</span> : null}
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        ) : isSingleOptionFinalApprove ? null : options.length > 0 ? (
          <div className={mobile ? "plan-opts" : "dt-planopts"} role="radiogroup" aria-label="Plan options">
            {options.map((option) => {
              const on = option.id === selectedId;
              return (
                <button
                  key={option.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className={`${mobile ? "plan-opt" : "dt-planopt"}${on ? ` ${mobile ? "plan-opt-on" : "dt-planopt-on"}` : ""}`}
                  onClick={() => !resolving && setSelectedId(option.id)}
                  disabled={resolving}
                >
                  <span className={mobile ? "plan-opt-radio" : "dt-planopt-radio"} aria-hidden="true" />
                  <span className={mobile ? "plan-opt-body" : "dt-planopt-body"}>
                    <span className={mobile ? "plan-opt-top" : "dt-planopt-top"}>
                      <span className={mobile ? "plan-opt-letter" : "dt-planopt-letter"}>{option.letter}</span>
                      <span className={mobile ? "plan-opt-label" : "dt-planopt-label"}>{option.label}</span>
                    </span>
                    {option.description ? <span className={mobile ? "plan-opt-text" : "dt-planopt-text"}>{option.description}</span> : null}
                  </span>
                </button>
              );
            })}
          </div>
        ) : null}
        <div className={mobile ? "plan-prop-actions" : "dt-planprop-actions"}>
          <button
            type="button"
            className={mobile ? "plan-prop-approve" : "dt-planprop-approve"}
            onClick={() => { void resolve("approve"); }}
            disabled={
              resolving
              || (
                !isSingleOptionFinalApprove
                && (multiQuestions.length > 0 ? !allQuestionsAnswered : !selected)
              )
            }
          >
            <Check size={14} strokeWidth={2.4} aria-hidden="true" />
            {isSingleOptionFinalApprove ? PLAN_APPROVAL_VISIBLE_TEXT : "Confirm"}
          </button>
          <button
            type="button"
            className={mobile ? "plan-prop-keep" : "dt-planprop-keep"}
            onClick={() => { void resolve("deny"); }}
            disabled={resolving}
          >
            Keep planning
          </button>
        </div>
      </div>
      <div className={mobile ? "thr-meta" : "dt-bubble-meta"}>
        {isSingleOptionFinalApprove ? "Awaiting your approval" : "Pick a plan · awaiting your approval"}
      </div>
    </div>
  );
}

function interactionRequestDetailText(request: InteractionRequest, key: string): string | null {
  const value = request.details?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isVisiblePlanProposalRequest(request: InteractionRequest): boolean {
  return request.kind === "plan_proposal" && request.status === "pending";
}

function planProposalRequestMatchesTurn(request: InteractionRequest, turn: BroTimelineTurn): boolean {
  if (!isVisiblePlanProposalRequest(request)) return false;
  const requestClientId = interactionRequestDetailText(request, "client_request_id");
  return request.task_id === turn.task?.task_id
    || request.run_id === turn.task?.run_id
    || request.task_id === turn.metadata?.task_id
    || request.run_id === turn.metadata?.run_id
    || (requestClientId !== null && requestClientId === turn.client_request_id);
}

function planProposalRequestMatchesThread(
  request: InteractionRequest,
  broId: string,
  threadId: string | null,
  turns: BroTimelineTurn[],
): boolean {
  if (!isVisiblePlanProposalRequest(request) || threadId === null) return false;
  const personaId = interactionRequestDetailText(request, "persona_id");
  if (personaId !== null && personaId !== broId) return false;
  const targetThreadId = interactionRequestDetailText(request, "target_thread_id");
  if (targetThreadId !== null) return targetThreadId === threadId;
  return turns.some((turn) => timelineTurnMatchesThread(turn, broId, threadId) && planProposalRequestMatchesTurn(request, turn));
}

function inlinePlanProposalRequestIds(requests: InteractionRequest[], turns: BroTimelineTurn[]): Set<string> {
  const ids = new Set<string>();
  for (const request of requests) {
    if (turns.some((turn) => planProposalRequestMatchesTurn(request, turn))) {
      ids.add(request.request_id);
    }
  }
  return ids;
}

function unplacedPlanProposalRequests(
  requests: InteractionRequest[],
  broId: string,
  threadId: string | null,
  turns: BroTimelineTurn[],
): InteractionRequest[] {
  const inlineIds = inlinePlanProposalRequestIds(requests, turns);
  return requests.filter((request) => (
    !inlineIds.has(request.request_id)
    && planProposalRequestMatchesThread(request, broId, threadId, turns)
  ));
}

function ConversationMessageBubble({ bro, message, mobile = false }: { bro: BroCardModel; message: ChatMessage; mobile?: boolean }) {
  const prefix = mobile ? "thr" : "dt";
  const metaClass = mobile ? "thr-meta" : "dt-bubble-meta";
  const isUser = message.role === "user";
  return (
    <div className={`${prefix}-turn ${isUser ? `${prefix}-turn-you` : `${prefix}-turn-bro`}`}>
      {isUser && message.planMode ? (
        <span className={`${prefix}-plantag`} aria-label="Sent in plan mode">
          <GitBranch size={12} strokeWidth={2.2} aria-hidden="true" />
          Plan mode
        </span>
      ) : null}
      <div className={`${prefix}-bubble ${isUser ? `${prefix}-bubble-you${message.planMode ? ` ${prefix}-bubble-plan` : ""}` : `${prefix}-bubble-bro`}`}>
        <MarkdownText>{message.text}</MarkdownText>
      </div>
      <div className={metaClass}>
        <MessageMeta label={isUser ? "You" : bro.name} />
      </div>
    </div>
  );
}

function timelineStatusLabel(status: string): string {
  const normalized = status?.replace(/_/g, " ").trim();
  return normalized || "completed";
}

function timelineTaskStatus(status: string): BroTaskRecord["status"] {
  if (status === "failed") return "failed";
  if (status === "cancelled" || status === "canceled") return "cancelled";
  if (status === "running" || status === "inProgress" || status === "pending") return "running";
  return "completed";
}

function timelineMessageText(message: BroTimelineMessage | null): string {
  if (!message) return "";
  return (message.kind === "audio" ? message.transcript : message.text)?.trim() ?? "";
}

function timelineMetadataText(turn: BroTimelineTurn, key: string): string {
  const value = turn.metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function timelinePlanMode(turn: BroTimelineTurn): boolean {
  return turn.metadata?.plan_mode === true || turn.user?.metadata?.plan_mode === true || turn.task?.metadata?.plan_mode === true;
}

function normalizePlanStatus(value: unknown): NonNullable<BroTaskRecord["plan"]>["steps"][number]["status"] {
  if (typeof value === "string") {
    const normalized = value.replace(/[_-]/g, "").toLowerCase();
    if (normalized === "inprogress" || normalized === "running" || normalized === "active") return "inProgress";
    if (normalized === "completed" || normalized === "complete" || normalized === "done") return "completed";
  }
  return "pending";
}

function timelinePlan(value: unknown): BroTaskRecord["plan"] | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const raw = value as Record<string, unknown>;
  const text = typeof raw.text === "string" && raw.text.trim() ? raw.text.trim() : null;
  const explanation = typeof raw.explanation === "string" && raw.explanation.trim() ? raw.explanation.trim() : null;
  const steps = Array.isArray(raw.steps)
    ? raw.steps.flatMap((step) => {
        if (typeof step === "string") {
          const text = step.trim();
          return text ? [{ step: text, status: "pending" as const }] : [];
        }
        if (!step || typeof step !== "object" || Array.isArray(step)) return [];
        const item = step as Record<string, unknown>;
        const label = typeof item.step === "string" ? item.step.trim() : "";
        return label ? [{ step: label, status: normalizePlanStatus(item.status) }] : [];
      })
    : [];
  if (!text && !explanation && steps.length === 0) return undefined;
  return { text, explanation, steps };
}

function TimelineUserMessage({ bro, turn, mobile = false }: { bro: BroCardModel; turn: BroTimelineTurn; mobile?: boolean }) {
  const message = turn.user;
  if (!message) return null;
  if (message.kind === "audio") {
    return (
      <AudioTurnBubble
        bro={bro}
        mobile={mobile}
        turn={{
          id: message.audio_id ?? message.message_id,
          broId: turn.persona_id,
          threadId: turn.thread_id,
          status: message.status === "failed" ? "failed" : message.status === "sending" ? "sending" : "sent",
          durationMs: message.duration_ms ?? 0,
          createdAt: message.created_at ?? undefined,
          transcript: message.transcript ?? undefined,
        }}
      />
    );
  }
  const text = timelineMessageText(message);
  if (!text) return null;
  return (
    <ConversationMessageBubble
      bro={bro}
      message={{
        role: "user",
        text,
        id: message.message_id,
        planMode: timelinePlanMode(turn),
        createdAt: message.created_at ?? undefined,
      }}
      mobile={mobile}
    />
  );
}

function timelineTaskRecord(turn: BroTimelineTurn): BroTaskRecord | null {
  const task = turn.task;
  const assistantText = timelineMessageText(turn.assistant);
  const plan = task?.plan ?? timelinePlan(turn.metadata?.codex_plan);
  const goal = task?.goal?.trim() || timelineMetadataText(turn, "codex_goal");
  const status = timelineTaskStatus(task?.status ?? turn.status);
  if (!task && !assistantText && !plan && !goal) return null;
  return {
    taskId: task?.task_id ?? turn.turn_id,
    title: task?.title ?? (timelineMetadataText(turn, "assistant_title") || goal || turnUserText(turn) || "Codex update"),
    goal: goal || undefined,
    plan,
    status,
    statusLabel: timelineStatusLabel(task?.status_label ?? turn.assistant?.status ?? turn.status),
    progress: task?.progress ?? (status === "completed" ? 100 : status === "running" ? 60 : 30),
    description: task?.description ?? assistantText,
    summary: task?.summary ?? assistantText,
    timestamp: task?.updated_at ?? turn.assistant?.updated_at ?? turn.updated_at ?? undefined,
    timestampLabel: task?.updated_at ?? turn.assistant?.updated_at ?? turn.updated_at ?? undefined,
  };
}

function TimelineTurnView({
  bro,
  turn,
  mobile = false,
  onTextTurn,
  sessionId = null,
  workspaceRoot = null,
}: {
  bro: BroCardModel;
  turn: BroTimelineTurn;
  mobile?: boolean;
  onTextTurn?: (turn: TextTurn) => void;
  sessionId?: string | null;
  workspaceRoot?: string | null;
}) {
  const shell = useNewbroShell();
  const record = timelineTaskRecord(turn);
  const proposalRequests = shell.interactionRequests.filter((request) => planProposalRequestMatchesTurn(request, turn));

  // Reasoning bubble — rendered for in-flight turns (desktop + mobile) and collapsed pill for settled mobile turns.
  const taskId = turn.task?.task_id ?? null;
  const activeRun = taskId
    ? (shell.executionRuns.find((r) => r.task_id === taskId && (r.status === "running" || r.status === "created" || r.status === "waiting_executor")) ?? null)
    : null;
  // For settled turns, find any run for this task (including completed runs).
  const anyRun = activeRun ?? (taskId ? (shell.executionRuns.find((r) => r.task_id === taskId) ?? null) : null);
  const details = taskId ? (shell.recentExecutionDetails[taskId] ?? null) : null;
  const nativeReasoningSteps = buildReasoningStepsForNativeTurn(turn, shell.recentNativeTurnReasoning);
  const nativeInFlight = nativeReasoningSteps.length > 0 && (turn.status === "running" || turn.status === "pending");
  const nativeSettled = nativeReasoningSteps.length > 0 && !nativeInFlight;
  const reasoningSteps = nativeInFlight ? nativeReasoningSteps : buildReasoningStepsForTurn(activeRun, details);
  const settledReasoningSteps = nativeSettled
    ? nativeReasoningSteps
    : activeRun
      ? []
      : buildReasoningStepsForTurn(anyRun, details);
  const answerText = timelineMessageText(turn.assistant) || record?.summary?.trim() || record?.description?.trim() || "";
  const rawAnswerItemId = turn.assistant?.metadata?.codex_item_id;
  const answerItemId = typeof rawAnswerItemId === "string" ? rawAnswerItemId : null;

  const liveState = deriveLiveTurnState({
    status: turn.status,
    stepCount: reasoningSteps.length,
    hasAnswer: answerText !== "",
  });
  // Codex multi-message turn split: while reasoning the latest step is the
  // prominent streaming commentary line and the rest are compact steps; on
  // answering/settled commentary collapses into the (deduped) step list and the
  // final answer is the answer. See lib/splitLiveSteps for the contract.
  const { activeCommentary, stepsForBubble, dedupedSettledSteps } = splitLiveSteps({
    liveState,
    reasoningSteps,
    settledReasoningSteps,
    answerItemId,
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = liveState.kind !== "settled" && stopTaskId !== null;
  const onStop = () => { if (stopTaskId) shell.cancelTask(stopTaskId); };

  const downloadContext =
    sessionId && turn.thread_id && turn.turn_id && workspaceRoot
      ? { sessionId, threadId: turn.thread_id, turnId: turn.turn_id, workspaceRoot }
      : undefined;
  const settledHasNothing =
    liveState.kind === "settled" && answerText === "" && dedupedSettledSteps.length === 0;

  return (
    <>
      <TimelineUserMessage bro={bro} turn={turn} mobile={mobile} />
      {settledHasNothing ? null : (
        <LiveTurnBubble
          broName={bro.name}
          state={liveState}
          steps={stepsForBubble}
          activeCommentary={activeCommentary}
          answer={answerText}
          mobile={Boolean(mobile)}
          canStop={canStop}
          onStop={onStop}
          downloadContext={downloadContext}
        />
      )}
      {proposalRequests.map((request) => (
        <PlanProposalCard
          key={request.request_id}
          request={request}
          mobile={mobile}
          broId={turn.persona_id}
          threadId={turn.thread_id}
          onTextTurn={onTextTurn}
        />
      ))}
    </>
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
    const transcript = transcripts.get(turn.audioInstructionId ?? "") ?? transcripts.get(turn.id);
    if (!transcript || turn.transcript === transcript) return turn;
    changed = true;
    return { ...turn, transcript };
  });
  return changed ? next : turns;
}

function activeCodexAudioState(
  shell: Pick<ReturnType<typeof useNewbroShell>, "runtimePersonas" | "executorNodes">,
  bro: BroCardModel,
): ActiveCodexAudioState {
  const persona = shell.runtimePersonas.find((candidate) => candidate.persona_id === bro.id);
  if (!persona?.executor_node_id) return { enabled: false, reason: "Bind and connect this Bro before recording." };
  const node = shell.executorNodes.find((candidate) => candidate.node_id === persona.executor_node_id);
  if (!node || node.connection_status !== "connected" || !node.connected_executors.includes("codex")) {
    return { enabled: false, reason: "Connect Codex on your computer before recording." };
  }
  const codexCapability = node.connected_executor_capabilities?.find(
    (capability) => capability.executor_type === "codex",
  );
  if (codexCapability && !codexCapability.supports_audio_instruction) {
    return { enabled: false, reason: "Enable local Whisper on your computer before recording." };
  }
  return { enabled: true, reason: "Hold to record audio" };
}

function activeCodexTextState(
  shell: Pick<ReturnType<typeof useNewbroShell>, "runtimePersonas" | "executorNodes">,
  bro: BroCardModel,
): ActiveCodexAudioState {
  const persona = shell.runtimePersonas.find((candidate) => candidate.persona_id === bro.id);
  if (!persona?.executor_node_id) return { enabled: false, reason: "Bind and connect this Bro before sending." };
  const node = shell.executorNodes.find((candidate) => candidate.node_id === persona.executor_node_id);
  if (!node || node.connection_status !== "connected" || !node.connected_executors.includes("codex")) {
    return { enabled: false, reason: "Connect Codex on your computer before sending." };
  }
  const codexCapability = node.connected_executor_capabilities?.find(
    (capability) => capability.executor_type === "codex",
  );
  if (codexCapability && !codexCapability.supports_follow_up) {
    return { enabled: false, reason: "Selected Bro's computer doesn't support text follow-up." };
  }
  return { enabled: true, reason: "Send directly to executor" };
}

function usePushToTalkAudio({
  sessionId,
  broId,
  targetThreadId,
  createNewThread,
  workspaceId,
  disabled,
  onTurn,
  onRemoveTurn,
  onError,
  onThreadResolved,
  onSent,
}: {
  sessionId: string | null;
  broId: string;
  targetThreadId: string | null;
  createNewThread: boolean;
  workspaceId?: string | null;
  disabled: boolean;
  onTurn: (turn: AudioTurn) => void;
  onRemoveTurn: (turnId: string) => void;
  onError: (message: string) => void;
  onThreadResolved: (threadId: string | null) => void;
  onSent: () => void | Promise<void>;
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
  const startingRef = useRef(false);

  async function start() {
    if (disabled || !sessionId || activeRef.current || startingRef.current) return;
    startingRef.current = true;
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
    } finally {
      startingRef.current = false;
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
        createNewThread,
        ...(workspaceId ? { workspaceId } : {}),
        pcm16: pcm.blob,
        durationMs: pcm.durationMs || durationMs,
        sampleRate: pcm.sampleRate,
        numChannels: pcm.numChannels,
        samplesPerChannel: pcm.samplesPerChannel,
        clientRequestId: active.turnId,
      });
      onTurn({
        id: active.turnId,
        audioInstructionId: response.audio_instruction_id,
        broId,
        threadId: response.target_thread_id ?? targetThreadId,
        status: "sent",
        durationMs: pcm.durationMs || durationMs,
        createdAt: active.createdAt,
        transcript: response.transcript_text?.trim() || undefined,
      });
      onThreadResolved(response.target_thread_id);
      await onSent();
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
  if (state === "offline") return bro.nodeName ? "computer offline" : "needs a computer";
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

function broDetailHref(broId: string, threadId?: string | null): string {
  if (typeof window === "undefined") return `/bros/${encodeURIComponent(broId)}`;
  const sid = new URLSearchParams(window.location.search).get("sid");
  const params = new URLSearchParams();
  if (sid) params.set("sid", sid);
  if (threadId) params.set("thread", threadId);
  const query = params.toString() ? `?${params.toString()}` : "";
  return `/bros/${encodeURIComponent(broId)}${query}`;
}

function clickedInsideHomeCardAction(event: MouseEvent<HTMLAnchorElement>): boolean {
  const target = event.target as Element | null;
  return Boolean(target && target.closest("[data-home-card-action]"));
}

function openBroFromHome(
  event: MouseEvent<HTMLAnchorElement>,
  broId: string,
  onOpen: (id: string, threadId?: string) => void,
  threadId?: string,
): void {
  if (clickedInsideHomeCardAction(event)) {
    event.preventDefault();
    return;
  }
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
  onOpen(broId, threadId);
}

function homeThreadSortTime(thread: BroThread): number {
  const parsed = thread.updated_at ? Date.parse(thread.updated_at) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function homeThreadTimeLabel(thread: BroThread): string {
  const parsed = thread.updated_at ? Date.parse(thread.updated_at) : Number.NaN;
  if (Number.isNaN(parsed)) return thread.status.replace(/_/g, " ");
  const minutes = Math.floor(Math.max(0, Date.now() - parsed) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(parsed));
}

function buildHomeRecents(threads: BroThread[], personas: Persona[]): HomeRecentItem[] {
  const personaNameById = new Map(personas.map((persona) => [persona.persona_id, persona.name]));
  return [...threads]
    .filter((thread) => personaNameById.has(thread.persona_id))
    .sort((a, b) => homeThreadSortTime(b) - homeThreadSortTime(a))
    .slice(0, 5)
    .map((thread) => ({
      id: thread.thread_id,
      broId: thread.persona_id,
      threadId: thread.thread_id,
      title: thread.title || "Current session",
      bro: personaNameById.get(thread.persona_id) ?? thread.persona_name ?? "NewBro",
      when: homeThreadTimeLabel(thread),
    }));
}

function Header({
  active,
  bro,
  onHome,
  onLogout,
  account,
  onConnect,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  onHome: () => void;
  onLogout: () => void;
  account: string;
  onConnect?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const tone = bro ? homeBroTone(homeBroState(bro)) : "calm";
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
              </span>
              <span>{bro.name}</span>
            </button>
          </>
        ) : null}
      </div>
      <div className="dt-header-r">
        {bro ? (
          detailPaused && onConnect ? (
            <button type="button" className="dt-header-pill dt-header-pill-paused dt-header-pill-action" onClick={onConnect}>
              <span className="dt-header-pill-dot" />
              computer offline · set up
            </button>
          ) : (
            <span className={`dt-header-pill ${detailPaused ? "dt-header-pill-paused" : "dt-header-pill-live"}`}>
              <span className="dt-header-pill-dot" />
              {detailPaused ? "paused · computer offline" : "live · listening"}
            </span>
          )
        ) : null}
        <div className="dt-header-account-wrap">
          <button
            type="button"
            className="dt-header-account dt-header-account-btn"
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span className="dt-header-account-avatar">{account.trim().charAt(0).toUpperCase() || "N"}</span>
            <span className="dt-header-account-name">{account}</span>
          </button>
          {menuOpen ? (
            <>
              <button
                type="button"
                className="dt-account-backdrop"
                aria-hidden="true"
                tabIndex={-1}
                onClick={() => setMenuOpen(false)}
              />
              <div className="dt-account-pop" role="dialog" aria-label="Account">
                <div className="dt-account-pop-email">{account}</div>
                <div className="dt-account-pop-section">
                  <div className="dt-account-pop-eyebrow">DEVICES</div>
                  <p className="dt-account-pop-hint">Pair a Cardputer or other device using the code shown on its screen.</p>
                  <DevicePairingForm onClaim={claimDevice} />
                </div>
              </div>
            </>
          ) : null}
        </div>
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
  onConnect,
}: {
  active: RuntimePage;
  bro?: BroCardModel | null;
  children: React.ReactNode;
  onHome: () => void;
  onConnect?: () => void;
}) {
  const shell = useNewbroShell();
  return (
    <div className="dt-frame min-h-dvh">
      <div className="dt-shell min-h-dvh">
        <Header
          active={active}
          bro={bro}
          onHome={onHome}
          account={shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in"}
          onLogout={() => { void shell.logout(); }}
          onConnect={onConnect}
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

function DesktopBroCard({
  bro,
  onOpen,
  onSetup,
  onRename,
  featured = false,
}: {
  bro: BroCardModel;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
  onRename: (bro: BroCardModel) => void;
  featured?: boolean;
}) {
  const state = homeBroState(bro);
  const tone = homeBroTone(state);
  const handleRename = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onRename(bro);
  };
  return (
    <a data-testid={`bro-card-${bro.id}`} className={`dt-bro-card dt-bro-card-${tone}${featured ? " dt-bro-card-featured" : ""}`} href={broDetailHref(bro.id)} onClickCapture={(event) => { if (clickedInsideHomeCardAction(event)) event.preventDefault(); }} onClick={(event) => openBroFromHome(event, bro.id, onOpen)}>
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
        </div>
        {state === "working" && (bro.latestReasoningStep || bro.progressLabel) ? (
          <div className="dt-bro-card-reasoning">
            <span className="dt-bro-card-reasoning-orb" aria-hidden="true"><span /><span /><span /></span>
            <span className="dt-bro-card-reasoning-text">{bro.latestReasoningStep || bro.progressLabel}</span>
          </div>
        ) : null}
        {bro.source === "runtime" ? (
          <button type="button" data-home-card-action="rename" className="nb-bro-edit-button dt-bro-card-edit" aria-label={`Edit ${bro.name}`} onClick={handleRename}>
            <Pencil size={13} strokeWidth={2.1} aria-hidden="true" />
          </button>
        ) : null}
        <HomeBroConnectAction bro={bro} variant="card" onSetup={onSetup} />
      </div>
      <span className="dt-bro-card-arrow">›</span>
    </a>
  );
}

function DesktopRosterRow({
  bro,
  onOpen,
  onSetup,
  onRename,
}: {
  bro: BroCardModel;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
  onRename: (bro: BroCardModel) => void;
}) {
  const state = homeBroState(bro);
  const handleRename = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onRename(bro);
  };
  return (
    <a data-testid={`bro-card-${bro.id}`} className={`dt-roster-row dt-roster-row-${state}`} href={broDetailHref(bro.id)} onClickCapture={(event) => { if (clickedInsideHomeCardAction(event)) event.preventDefault(); }} onClick={(event) => openBroFromHome(event, bro.id, onOpen)}>
      <div className={`dt-roster-avatar dt-roster-avatar-${state}`}>
        <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={26} />
      </div>
      <span className="dt-roster-name">{bro.name}</span>
      <span className="dt-roster-last">{homeBroLast(bro, state)}</span>
      {bro.source === "runtime" ? (
        <button type="button" data-home-card-action="rename" className="nb-bro-edit-button dt-roster-edit" aria-label={`Edit ${bro.name}`} onClick={handleRename}>
          <Pencil size={13} strokeWidth={2.1} aria-hidden="true" />
        </button>
      ) : null}
      <HomeBroConnectAction bro={bro} variant="row" onSetup={onSetup} />
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
          A <strong>bro</strong> is a teammate that works on a computer
          you trust. Give it a name, connect a computer, and it&rsquo;ll start
          working alongside you.
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

function RenameBroDialog({
  bro,
  sessionId,
  onClose,
  onRenamed,
  mobile = false,
}: {
  bro: BroCardModel;
  sessionId: string;
  onClose: () => void;
  onRenamed: () => Promise<void>;
  mobile?: boolean;
}) {
  const [name, setName] = useState(bro.name);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmedName = name.trim();
  const unchanged = trimmedName === bro.name.trim();
  const canSave = trimmedName.length > 0 && !unchanged && !pending;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    if (!trimmedName) {
      setError("Bro name is required.");
      return;
    }
    if (unchanged) {
      onClose();
      return;
    }
    setPending(true);
    setError(null);
    try {
      await updatePersona(sessionId, bro.id, { name: trimmedName });
      await onRenamed();
      onClose();
      return;
    } catch (err) {
      setError(describeError(err, "Could not rename this Bro."));
      setPending(false);
    }
  };

  return (
    <div
      className="nb-first-run-sheet-layer nb-rename-dialog-layer"
      role="dialog"
      aria-modal="true"
      aria-label={`Edit ${bro.name}`}
      onMouseDown={(event) => {
        if (!pending && event.target === event.currentTarget) onClose();
      }}
    >
      <form className={`nb-rename-dialog${mobile ? " nb-rename-dialog-mobile" : ""}`} onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}>
        <header className="nb-rename-head">
          <div>
            <span className="ob-eyebrow ob-eyebrow-coral">BRO SETTINGS</span>
            <h2 className="nb-rename-title">Edit {bro.name}</h2>
          </div>
          <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose} disabled={pending}>
            <X size={16} strokeWidth={2.2} />
          </button>
        </header>
        <label className="ob-field">
          <span className="ob-field-eyebrow">BRO NAME</span>
          <div className={`ob-input${trimmedName ? " ob-input-filled" : ""}`}>
            <span className="ob-input-prefix">@</span>
            <input
              aria-label="Bro name"
              type="text"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              autoFocus
            />
          </div>
          <span className="ob-field-hint">Use a short name that is easy to say out loud.</span>
        </label>
        {error ? <div className="nb-status-banner nb-status-banner-error">{error}</div> : null}
        <footer className="nb-rename-actions">
          <button type="button" className="nb-rename-secondary" onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <button type="submit" className={`ob-cta${!canSave ? " ob-cta-pending" : ""}`} disabled={!canSave}>
            {pending ? <span className="ob-cta-spinner" aria-hidden="true" /> : null}
            <span>{pending ? "Saving..." : "Save"}</span>
          </button>
        </footer>
      </form>
    </div>
  );
}

function DesktopHome({ onOpenBro }: { onOpenBro: (id: string, threadId?: string) => void }) {
  const shell = useNewbroShell();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [setupBro, setSetupBro] = useState<BroCardModel | null>(null);
  const [renameBro, setRenameBro] = useState<BroCardModel | null>(null);
  const homeBros = useMemo(() => [...shell.bros].sort(compareHomeBros), [shell.bros]);
  const workingBros = homeBros.filter((bro) => homeBroState(bro) === "working");
  const standingByBros = homeBros.filter((bro) => homeBroState(bro) !== "working");
  const recents = buildHomeRecents(shell.broThreads, shell.runtimePersonas);
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
                  <p className="dt-page-sub">Open a bro to talk or read their thread. Sessions persist as long as the node stays online.</p>
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
                      {workingBros.map((bro) => <DesktopBroCard key={bro.id} bro={bro} featured onOpen={onOpenBro} onSetup={setSetupBro} onRename={setRenameBro} />)}
                    </div>
                  </section>
                ) : null}
                <section className="dt-home-section">
                  <div className="dt-home-section-head">
                    <span className="ob-eyebrow">STANDING BY · {standingByBros.length}</span>
                    <span className="dt-home-section-sub">Quiet for now — open one to start talking</span>
                  </div>
                  <div className="dt-bro-roster">
                    {standingByBros.map((bro) => <DesktopRosterRow key={bro.id} bro={bro} onOpen={onOpenBro} onSetup={setSetupBro} onRename={setRenameBro} />)}
                  </div>
                </section>
              </>
            </section>
            <aside className="dt-home-rail">
              <section className="dt-rail-block">
                <div className="dt-rail-block-head">
                  <span className="ob-eyebrow">RECENT</span>
                </div>
                {recents.length > 0 ? (
                  <ul className="dt-recent-list">
                    {recents.map((recent) => (
                      <li key={recent.id}>
                        <a
                          className="dt-recent"
                          href={broDetailHref(recent.broId, recent.threadId)}
                          onClick={(event) => openBroFromHome(event, recent.broId, onOpenBro, recent.threadId)}
                        >
                          <span className="dt-recent-icon"><FileText size={14} strokeWidth={1.9} /></span>
                          <span className="dt-recent-body">
                            <span className="dt-recent-title">{recent.title}</span>
                            <span className="dt-recent-meta"><span>{recent.bro}</span><span className="dt-bro-meta-sep">·</span><span>{recent.when}</span></span>
                          </span>
                        </a>
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
      {setupBro && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSetupBro(null)} onCreated={shell.refreshShellSession} bro={setupBro} />
      ) : null}
      {renameBro && shell.activeShellSessionId ? (
        <RenameBroDialog sessionId={shell.activeShellSessionId} bro={renameBro} onClose={() => setRenameBro(null)} onRenamed={shell.refreshShellSession} />
      ) : null}
    </DesktopFrame>
  );
}

function CreateConnectSheet({
  sessionId,
  onClose,
  onCreated,
  bro,
  mode,
  mobile = false,
}: {
  sessionId: string;
  onClose: () => void;
  onCreated: () => Promise<void>;
  bro?: BroCardModel | null;
  mode?: "setup" | "reconnect";
  mobile?: boolean;
}) {
  const initialBroName = bro?.name ?? "atlas";
  const [name, setName] = useState(initialBroName);
  const [savedBroName, setSavedBroName] = useState(initialBroName);
  const [commands, setCommands] = useState<ExecutorConnectCommands | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nameSaving, setNameSaving] = useState(false);
  const [copiedKind, setCopiedKind] = useState<"install" | "run" | "settings" | null>(null);
  const [pendingNodeId, setPendingNodeId] = useState<string | null>(null);
  const [pendingBroName, setPendingBroName] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const [showTerminal, setShowTerminal] = useState(false);
  const finalizingRef = useRef(false);
  const autoIssueStartedRef = useRef(false);
  const trimmedName = name.trim();
  const existingBroNameDirty = Boolean(bro) && trimmedName !== savedBroName.trim();
  const existingBroNameChanged = existingBroNameDirty && trimmedName.length > 0;
  const connectActionsDisabled = existingBroNameDirty || nameSaving;
  const canCreate = trimmedName.length > 0 && !busy && !nameSaving && !commands && !pendingNodeId && !completed;
  const canSaveExistingBroName = Boolean(bro) && existingBroNameChanged && !busy && !nameSaving && !completed;
  const reconnectExistingBro = Boolean(bro?.nodeName) && mode !== "setup";

  // For an existing bro that already has a node, reveal its connect command as
  // soon as the dialog opens, so the command + copy work without a "create" click.
  useEffect(() => {
    const nodeId = bro?.executorNodeId;
    if (!nodeId || commands) return;
    let cancelled = false;
    void (async () => {
      try {
        const issue = await revealExecutorNodeConnectCommand(sessionId, nodeId);
        if (cancelled) return;
        setCommands(buildExecutorConnectCommands(issue.node.node_id, issue.token, {
          enabledExecutors: issue.node.enabled_executors,
          acpxAgent: issue.node.acpx_agent,
        }));
      } catch (err) {
        if (!cancelled) setError(describeError(err, "Could not load the connect command for this Bro."));
      }
    })();
    return () => { cancelled = true; };
  }, [bro?.executorNodeId, commands, sessionId]);

  async function saveExistingBroNameIfChanged(): Promise<boolean> {
    if (!bro) return true;
    if (nameSaving) return false;
    if (!trimmedName) {
      setError("Bro name is required.");
      return false;
    }
    if (!existingBroNameChanged) {
      return true;
    }
    setNameSaving(true);
    setError(null);
    try {
      await updatePersona(sessionId, bro.id, { name: trimmedName });
      await onCreated();
      setSavedBroName(trimmedName);
      return true;
    } catch (err) {
      setError(describeError(err, "Could not rename this Bro."));
      return false;
    } finally {
      setNameSaving(false);
    }
  }

  async function copyCommand(value: string, kind: "install" | "run" | "settings") {
    await navigator.clipboard?.writeText(value).then(() => setCopiedKind(kind), () => setCopiedKind(null));
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

  async function issueConnectCredentials({ copyInstall }: { copyInstall: boolean }) {
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      if (!(await saveExistingBroNameIfChanged())) {
        return;
      }
      const nextBroName = trimmedName;
      const issue = bro?.executorNodeId
        ? await revealExecutorNodeConnectCommand(sessionId, bro.executorNodeId)
        : await createExecutorNode(sessionId, { name: `${nextBroName} local node`, enabled_executors: ["codex"] });
      const nextCommands = buildExecutorConnectCommands(issue.node.node_id, issue.token, {
        enabledExecutors: issue.node.enabled_executors,
        acpxAgent: issue.node.acpx_agent,
      });
      setCommands(nextCommands);
      setPendingNodeId(issue.node.last_connected_at ? null : issue.node.node_id);
      setPendingBroName(nextBroName);
      setCompleted(false);
      if (copyInstall) {
        await copyCommand(nextCommands.installConnect, "install");
      }
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

  function createAndConnect() {
    void issueConnectCredentials({ copyInstall: true });
  }

  useEffect(() => {
    if (autoIssueStartedRef.current || bro || !canCreate) return;
    autoIssueStartedRef.current = true;
    void issueConnectCredentials({ copyInstall: false });
  }, [bro, canCreate]);

  useEffect(() => {
    if (!pendingNodeId || !pendingBroName || completed) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const nodes = await listExecutorNodes(sessionId);
        const node = nodes.find((candidate) => candidate.node_id === pendingNodeId);
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
              <h2 className="ob-sheet-h">{bro ? (reconnectExistingBro ? `Reconnect ${bro.name}` : `Set up ${bro.name}`) : "Set up your first bro"}</h2>
              <p className="ob-sheet-intro">{bro ? (reconnectExistingBro ? `Get ${bro.name} back online — install the Newbro app on its Mac and copy the connect settings.` : `Install the Newbro app on the Mac that runs ${bro.name}, then copy the connect settings.`) : "A bro works on a Mac you keep on. Three quick steps and it’s ready."}</p>
            </div>
            <button type="button" className="ob-sheet-close" aria-label="Close" onClick={onClose}><X size={16} strokeWidth={2.2} /></button>
          </header>
          <div className="ob-sheet-body">
            <div className="dt-modal-cols nb-create-connect-cols">
              <div className="dt-modal-col">
                <div className="ob-fieldset">
                  <label className="ob-field">
                    <span className="ob-field-eyebrow">STEP 1 · NAME IT</span>
                    <div className="ob-input ob-input-filled">
                      <span className="ob-input-prefix">@</span>
                      <input
                        aria-label="Bro name"
                        type="text"
                        value={name}
                        disabled={busy || nameSaving || completed}
                        onChange={(event) => setName(event.target.value)}
                      />
                    </div>
                    <span className="ob-field-hint">Pick one word that&rsquo;s easy to say out loud — you&rsquo;ll talk to it by name. e.g. atlas, scout, forge.</span>
                  </label>
                  {bro ? (
                    <button
                      type="button"
                      className="nb-inline-save-name"
                      disabled={!canSaveExistingBroName}
                      onClick={() => { void saveExistingBroNameIfChanged(); }}
                    >
                      {nameSaving ? "Saving..." : "Save name"}
                    </button>
                  ) : null}
                </div>
                <div className="ob-fieldset">
                  <span className="ob-field-eyebrow ob-fieldset-eyebrow">STEP 2 · AGENT CLIENT</span>
                  <div className="ob-exec-grid">
                    <div className="ob-exec-card ob-exec-card-on">
                      <span className="ob-exec-name">Codex</span>
                      <span className="ob-exec-desc">OpenAI&rsquo;s coding agent</span>
                      <span className="ob-exec-check" aria-hidden="true"><Check size={11} strokeWidth={2.8} /></span>
                    </div>
                    <div className="ob-exec-card ob-exec-card-soon" aria-disabled="true">
                      <span className="ob-exec-name">Hermes</span>
                      <span className="ob-exec-desc">Open-source agent by Nous Research</span>
                      <span className="ob-exec-card-soon-badge">Coming soon</span>
                    </div>
                  </div>
                  <span className="ob-field-hint">Pick the one you already use — newbro runs your tasks through it. You can switch anytime.</span>
                </div>
                <div className="ob-fieldset">
                  <span className="ob-field-eyebrow ob-fieldset-eyebrow">STEP 3 · DOWNLOAD THE APP</span>
                  {mobile ? (
                    <p className="ob-connect-guide">Install the Newbro app on the Mac that will run {pendingBroName || trimmedName || "your bro"}.</p>
                  ) : (
                    <>
                      <p className="ob-connect-guide">On the Mac where {pendingBroName || trimmedName || "your bro"} should work, install the Newbro app:</p>
                      <a className="ob-download" href={APP_DOWNLOAD_URL} target="_blank" rel="noreferrer">
                        <Download size={14} strokeWidth={2} />
                        Download the Newbro app
                      </a>
                    </>
                  )}
                </div>
              </div>

              <div className="dt-modal-col">
                <div className="ob-fieldset">
                  <span className="ob-field-eyebrow ob-fieldset-eyebrow">STEP 4 · COPY CONNECT SETTINGS</span>
                  <p className="ob-connect-guide">Copy the connect settings. If the Newbro app is running on this Mac, it applies them automatically.</p>
                  <div className="ob-connect">
                    <div className="ob-connect-cmd">
                      <span className="ob-connect-prompt">url</span>
                      <span className="ob-connect-line">{commands?.connectSettings ?? "Connect settings will appear after credentials are issued."}</span>
                      <button type="button" className="ob-connect-copy" aria-label="Copy connect settings" disabled={!commands || connectActionsDisabled} onClick={() => { if (commands && !connectActionsDisabled) void copyCommand(commands.connectSettings, "settings"); }}>
                        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="9" y="9" width="11" height="11" rx="2"/>
                          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                        </svg>
                      </button>
                    </div>
                    <div className="ob-connect-status">
                      <span className="ob-connect-spinner" aria-hidden="true"><span /><span /><span /></span>
                      <span className="ob-connect-status-text">
                        <strong>{completed ? `${pendingBroName || trimmedName} is connected.` : commands ? `Waiting to hear from your computer…` : `Ready to connect ${trimmedName || "a bro"}...`}</strong>
                        <span>{completed ? "The bro has been created after the computer connected successfully." : commands ? `This updates on its own once ${pendingBroName || trimmedName} connects. Nothing else on that Mac changes.` : "Newbro will issue a connect command first. The bro appears after the first successful connection."}</span>
                      </span>
                      <span className="ob-connect-time">{completed ? "done" : copiedKind ? "copied" : commands ? "waiting" : "new"}</span>
                    </div>
                  </div>
                  <button type="button" className={`ob-terminal-toggle${showTerminal ? " ob-terminal-toggle-open" : ""}`} aria-expanded={showTerminal} onClick={() => setShowTerminal((v) => !v)}>
                    <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
                    {showTerminal ? "Hide terminal option" : "Not on a Mac? Connect from a terminal"}
                  </button>
                  {showTerminal ? (
                    <div className="ob-terminal-fallback">
                      <p className="ob-connect-guide">Install — paste this in a terminal on that computer:</p>
                      <div className="ob-connect">
                        <div className="ob-connect-cmd">
                          <span className="ob-connect-prompt">$</span>
                          <span className="ob-connect-line">{commands?.installOnly ?? "curl -fsSL newbro.dev/install.sh | sh"}</span>
                          <button type="button" className="ob-connect-copy" aria-label="Copy install command" disabled={!commands || connectActionsDisabled} onClick={() => { if (commands && !connectActionsDisabled) void copyCommand(commands.installOnly, "install"); }}>
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="9" y="9" width="11" height="11" rx="2"/>
                              <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                            </svg>
                          </button>
                        </div>
                      </div>
                      <p className="ob-connect-guide ob-connect-guide-2">Then start it with your one-time key:</p>
                      <div className="ob-connect">
                        <div className="ob-connect-cmd">
                          <span className="ob-connect-prompt">$</span>
                          <span className="ob-connect-line">{commands?.runOnly ?? "Run command will appear after credentials are issued."}</span>
                          <button type="button" className="ob-connect-copy" aria-label="Copy connect command from terminal" disabled={!commands || connectActionsDisabled} onClick={() => { if (commands && !connectActionsDisabled) void copyCommand(commands.runOnly, "run"); }}>
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="9" y="9" width="11" height="11" rx="2"/>
                              <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="dt-modal-tip">
                  <span className="dt-modal-tip-eyebrow">TIP</span>
                  <p>
                    That computer should be a Mac that stays on — your main machine, a spare
                    laptop, a mini in the closet. {pendingBroName || trimmedName || "your bro"} only runs there when you ask
                    it to. (Linux or a server? Use the terminal option above.)
                  </p>
                </div>
              </div>
            </div>
            {error ? <div className="nb-status-banner nb-status-banner-error">{error}</div> : null}
          </div>
          <footer className="ob-sheet-foot">
            <span className="dt-modal-foot-status nb-create-connect-foot-status">
              <span className="dt-modal-foot-dot" />
              {completed ? "Connected once · Bro ready" : commands ? "We’ll detect your computer automatically · link valid 9:46" : "Download link + connect settings will be generated on demand"}
            </span>
            {commands && (completed || bro?.executorNodeId) ? (
              <button type="button" data-testid="bro-setup-done" className="ob-cta ob-cta-block" disabled={connectActionsDisabled} onClick={() => { if (!connectActionsDisabled) void onCreated().finally(onClose); }}>
                Done
              </button>
            ) : (
              <button type="button" data-testid="bro-setup-create-node" className={`ob-cta ob-cta-block${busy ? " ob-cta-pending" : ""}`} disabled={!canCreate} onClick={() => { void createAndConnect(); }}>
                {busy ? <span className="ob-cta-spinner" aria-hidden="true" /> : null}
                <span>{busy ? "Preparing..." : commands ? "Waiting for your computer…" : "Create and connect"}</span>
              </button>
            )}
          </footer>
        </section>
      </div>
    </div>
  );
}


function HomeBroConnectAction({ bro, variant, onSetup }: { bro: BroCardModel; variant: "card" | "row"; onSetup: (bro: BroCardModel) => void }) {
  if (bro.source !== "runtime") return null;
  if (bro.liveState !== "offline" && bro.liveState !== "unbound") return null;
  const label = bro.nodeName ? "Reconnect" : "Set up";
  const handle = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onSetup(bro);
  };
  return (
    <button
      type="button"
      data-testid={`home-bro-connect-${bro.id}`}
      data-home-card-action="connect"
      className={variant === "card" ? "dt-bro-card-copy" : "dt-roster-copy"}
      onClick={handle}
    >
      <Plus size={12} strokeWidth={2} />
      <span>{label}</span>
    </button>
  );
}

function OfflineBanner({
  bro,
  node,
  neverConnected = false,
  onConnect,
  mobile,
}: {
  bro: BroCardModel;
  node: ExecutorNodeRecord;
  neverConnected?: boolean;
  onConnect: () => void;
  mobile?: boolean;
}) {
  const title = neverConnected ? `${node.name} isn't connected yet` : `${node.name} is offline`;
  const body = neverConnected
    ? `Set it up in the Newbro app — ${bro.name} can take messages once it connects.`
    : `${bro.name} can't take new messages until this computer reconnects. Your draft is saved — the last turn retries on its own.`;
  const action = neverConnected ? "Set up" : "Reconnect";

  if (mobile) {
    return (
      <section data-testid="bro-node-disconnected-warning" className="ob-offline-banner dt-offline-banner nb-artboard-offline">
        <span className="ob-offline-banner-icon" aria-hidden="true">
          <WifiOff size={16} strokeWidth={2} />
        </span>
        <div className="ob-offline-banner-body">
          <strong>{title}</strong>
          <span>{body}</span>
          <button type="button" className="ob-offline-action" onClick={onConnect}>{action} with the app</button>
        </div>
      </section>
    );
  }

  return (
    <section data-testid="bro-node-disconnected-warning" className="dt-offline-notice nb-artboard-offline">
      <div className="dt-offline-notice-head">
        <span className="dt-offline-notice-icon" aria-hidden="true">
          <WifiOff size={17} strokeWidth={2} />
        </span>
        <div className="dt-offline-notice-copy">
          <strong>{title}</strong>
          <span>{body}</span>
        </div>
        {!neverConnected ? (
          <span className="dt-offline-notice-status" aria-hidden="true">
            <span className="dt-offline-notice-pip" />
            Auto-retrying
          </span>
        ) : null}
      </div>
      <div className="dt-offline-foot">
        <button type="button" className="ob-offline-action" onClick={onConnect}>{action} with the app</button>
      </div>
    </section>
  );
}

function ThreadPanel({
  bro,
  textTurns,
  audioTurns,
  timelineTurns,
  selectedThread,
  onTextTurn,
  disabled,
  disabledReason,
  hasOlderTimeline,
  onLoadOlderTimeline,
}: {
  bro: BroCardModel;
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  timelineTurns: BroTimelineTurn[];
  selectedThread: BroThreadRecord | null;
  onTextTurn?: (turn: TextTurn) => void;
  disabled?: boolean;
  disabledReason?: string | null;
  hasOlderTimeline?: boolean;
  onLoadOlderTimeline?: () => void;
}) {
  const shell = useNewbroShell();
  const draftText = shell.draftSession?.current_draft?.text ?? "";
  const renderedTurns = buildTimelineTurns({ timelineTurns, textTurns, audioTurns, broId: bro.id, threadId: selectedThread?.threadId ?? null });
  const fallbackProposalRequests = unplacedPlanProposalRequests(
    shell.interactionRequests,
    bro.id,
    selectedThread?.threadId ?? null,
    renderedTurns,
  );
  const hasContent = Boolean(draftText) || renderedTurns.length > 0 || fallbackProposalRequests.length > 0;
  const timelineLoading = selectedThread?.timelineStatus === "loading";
  const timelineLoadError = selectedThread?.timelineStatus === "failed" ? selectedThread.timelineError : null;
  const showEmptyState = !hasContent
    && !shell.openingThreadId
    && !timelineLoading
    && !shell.threadOpenError
    && !timelineLoadError
    && !(disabled && disabledReason);

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
        <div className="dt-turn dt-turn-sys" aria-busy="true">
          <div className="dt-sys-event">
            <span className="dt-sys-event-spin" aria-hidden="true" />
            <span>Fetching thread history…</span>
          </div>
        </div>
      ) : null}
      {timelineLoading && !shell.openingThreadId ? (
        <div className="dt-turn dt-turn-sys" aria-busy="true">
          <div className="dt-sys-event">
            <span className="dt-sys-event-spin" aria-hidden="true" />
            <span>Fetching thread history…</span>
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
      {timelineLoadError ? (
        <div className="dt-turn dt-turn-sys">
          <div className="dt-sys-event">
            <span className="dt-sys-event-dot" />
            <span>{timelineLoadError}</span>
          </div>
        </div>
      ) : null}
      {showEmptyState ? (
        <div className="dt-thread-empty" role="status">
          <span className="dt-thread-empty-eyebrow">No messages with {bro.name} yet</span>
          <span className="dt-thread-empty-hint">Type below or hold space to talk.</span>
        </div>
      ) : null}
      {hasContent ? <div className="dt-thread-day"><span>Current session</span></div> : null}
      {hasOlderTimeline ? (
        <button type="button" className="dt-thread-more" onClick={onLoadOlderTimeline}>
          <Layers size={12} strokeWidth={2.2} aria-hidden="true" />
          <span>Load older</span>
        </button>
      ) : null}
      {draftText ? (
        <div className="dt-turn dt-turn-you">
          <div className="dt-bubble dt-bubble-you">{draftText}</div>
          <div className="dt-bubble-meta">Draft · ready to send</div>
        </div>
      ) : null}
      {renderedTurns.map((turn) => (
        <TimelineTurnView
          key={timelineRowKey(turn)}
          bro={bro}
          turn={turn}
          onTextTurn={onTextTurn}
          sessionId={shell.activeShellSessionId}
          workspaceRoot={selectedThread?.workspaceId ?? null}
        />
      ))}
      {fallbackProposalRequests.map((request) => (
        <PlanProposalCard
          key={request.request_id}
          request={request}
          broId={bro.id}
          threadId={selectedThread?.threadId ?? null}
          onTextTurn={onTextTurn}
        />
      ))}
    </>
  );
}

function MobileThreadSurface({
  bro,
  selectedThreadId,
  selectedThread,
  createNewThread,
  workspaceId,
  textTurns,
  audioTurns,
  timelineTurns,
  onTextTurn,
  onAudioTurn,
  onRemoveAudioTurn,
  onThreadResolved,
  disabled,
  disabledReason,
}: {
  bro: BroCardModel;
  selectedThreadId: string | null;
  selectedThread: BroThreadRecord | null;
  createNewThread: boolean;
  workspaceId?: string | null;
  textTurns: TextTurn[];
  audioTurns: AudioTurn[];
  timelineTurns: BroTimelineTurn[];
  onTextTurn: (turn: TextTurn) => void;
  onAudioTurn: (turn: AudioTurn) => void;
  onRemoveAudioTurn: (turnId: string) => void;
  onThreadResolved: (threadId: string | null) => void;
  disabled?: boolean;
  disabledReason?: string | null;
}) {
  const shell = useNewbroShell();
  const [draft, setDraft] = useState("");
  const [planMode, setPlanMode] = useState(false);
  const threadBodyRef = useRef<HTMLElement | null>(null);
  const draftText = draft;
  const connected = shell.voiceSession.phase === "connected";
  const loading = shell.voiceSession.phase === "loading";
  const [inputMode, setInputMode] = useState<"ptt" | "free">("ptt");
  const audioState = activeCodexAudioState(shell, bro);
  const textState = activeCodexTextState(shell, bro);
  const needsWorkspace = createNewThread && !workspaceId;
  const textDisabled = Boolean(disabled) || !textState.enabled || needsWorkspace;
  const micDisabled = Boolean(disabled) || !audioState.enabled || needsWorkspace;
  const recorder = usePushToTalkAudio({
    sessionId: shell.activeShellSessionId,
    broId: bro.id,
    targetThreadId: selectedThreadId,
    createNewThread,
    workspaceId,
    disabled: micDisabled,
    onTurn: onAudioTurn,
    onRemoveTurn: onRemoveAudioTurn,
    onError: shell.setShellError,
    onThreadResolved,
    onSent: shell.refreshShellSession,
  });

  function submitText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitDraftText();
  }

  async function submitDraftText() {
    const text = draft.trim();
    if (needsWorkspace) {
      shell.setShellError("Choose a workspace before starting a new Codex thread.");
      return;
    }
    if (!text || textDisabled || !shell.activeShellSessionId) return;
    const turnId = `text-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const createdAt = new Date().toISOString();
    const startedAt = performance.now();
    directExecutorMetric("ui.text.submit.started", {
      client_request_id: turnId,
      session_id: shell.activeShellSessionId,
      bro_id: bro.id,
      target_thread_id: selectedThreadId,
      create_new_thread: createNewThread,
      text_length: text.length,
      plan_mode: planMode,
    });
    onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "sending", createdAt, planMode });
    directExecutorMetric("ui.text.local_turn_rendered", {
      client_request_id: turnId,
      elapsed_ms: Math.round(performance.now() - startedAt),
    });
    setDraft("");
    try {
      const response = await submitExecutorTextInstruction(shell.activeShellSessionId, {
        targetPersonaId: bro.id,
        targetThreadId: selectedThreadId,
        createNewThread,
        ...(workspaceId ? { workspaceId } : {}),
        clientRequestId: turnId,
        ...(planMode ? { planMode: true } : {}),
        text,
      });
      directExecutorMetric("ui.text.http.accepted", {
        client_request_id: turnId,
        instruction_id: response.instruction_id,
        target_thread_id: response.target_thread_id,
        elapsed_ms: Math.round(performance.now() - startedAt),
      });
      onThreadResolved(response.target_thread_id);
      onTextTurn({ id: turnId, broId: bro.id, threadId: response.target_thread_id ?? selectedThreadId, text, status: "sent", createdAt, planMode });
      await shell.refreshShellSession();
      directExecutorMetric("ui.text.refresh.completed", {
        client_request_id: turnId,
        instruction_id: response.instruction_id,
        elapsed_ms: Math.round(performance.now() - startedAt),
      });
    } catch (error: unknown) {
      const message = describeError(error, "Text could not be sent.");
      directExecutorMetric("ui.text.submit.failed", {
        client_request_id: turnId,
        elapsed_ms: Math.round(performance.now() - startedAt),
        error: message,
      });
      onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "failed", createdAt, error: message, planMode });
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

  const renderedTurns = buildTimelineTurns({ timelineTurns, textTurns, audioTurns, broId: bro.id, threadId: selectedThreadId });
  const fallbackProposalRequests = unplacedPlanProposalRequests(
    shell.interactionRequests,
    bro.id,
    selectedThreadId,
    renderedTurns,
  );
  const hasContent = Boolean(draftText) || renderedTurns.length > 0 || fallbackProposalRequests.length > 0;
  const timelineLoading = selectedThread?.timelineStatus === "loading";
  const timelineLoadError = selectedThread?.timelineStatus === "failed" ? selectedThread.timelineError : null;
  const showEmptyState = !hasContent
    && !shell.openingThreadId
    && !timelineLoading
    && !shell.threadOpenError
    && !timelineLoadError
    && !(disabled && disabledReason);
  const threadScrollVersion = [
    selectedThreadId ?? "new",
    renderedTurns.map((turn) => `${turn.turn_id}:${turn.status}:${turn.updated_at ?? ""}:${turn.assistant?.text ?? ""}`).join("|"),
    fallbackProposalRequests.map((request) => `${request.request_id}:${request.status}`).join("|"),
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
        {showEmptyState ? (
          <div className="dt-thread-empty" role="status">
            <span className="dt-thread-empty-eyebrow">No messages with {bro.name} yet</span>
            <span className="dt-thread-empty-hint">Type below or hold the mic to talk.</span>
          </div>
        ) : null}
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
        {timelineLoading && !shell.openingThreadId ? (
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
        {timelineLoadError ? (
          <div className="thr-turn thr-turn-sys">
            <div className="ob-sys-event">
              <span className="ob-sys-event-dot" />
              <span>{timelineLoadError}</span>
            </div>
          </div>
        ) : null}
        {selectedThreadId && shell.broTimelinePages[selectedThreadId]?.has_more ? (
          <button
            type="button"
            className="dt-thread-more"
            onClick={() => { void shell.loadMoreBroTimeline(bro.id, selectedThreadId); }}
          >
            <Layers size={12} strokeWidth={2.2} aria-hidden="true" />
            <span>Load older</span>
          </button>
        ) : null}
        {renderedTurns.map((turn) => (
          <TimelineTurnView
            key={timelineRowKey(turn)}
            bro={bro}
            turn={turn}
            mobile
            onTextTurn={onTextTurn}
            sessionId={shell.activeShellSessionId}
            workspaceRoot={selectedThread?.workspaceId ?? null}
          />
        ))}
        {fallbackProposalRequests.map((request) => (
          <PlanProposalCard
            key={request.request_id}
            request={request}
            mobile
            broId={bro.id}
            threadId={selectedThreadId}
            onTextTurn={onTextTurn}
          />
        ))}
      </main>
      <form className={`thr-composer nb-mobile-thread-composer${disabled ? " ob-composer-disabled" : ""}${planMode ? " thr-composer-plan" : ""}`} onSubmit={submitText}>
        {!disabled ? (
          <div className="mob-mode mob-mode-light" role="tablist" aria-label="Input mode">
            <button
              type="button"
              role="tab"
              aria-selected={inputMode === "ptt"}
              className={`mob-mode-btn${inputMode === "ptt" ? " mob-mode-btn-on" : ""}`}
              onClick={() => setInputMode("ptt")}
              title="Push to talk"
            >
              <span className="mob-mode-icon"><MessageSquare size={15} strokeWidth={2} /></span>
              <span className="mob-mode-label">Push to talk</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={inputMode === "free"}
              className={`mob-mode-btn${inputMode === "free" ? " mob-mode-btn-on" : ""}`}
              onClick={() => setInputMode("free")}
              title="Hands-free"
            >
              <span className="mob-mode-icon"><Radio size={15} strokeWidth={2} /></span>
              <span className="mob-mode-label">Hands-free</span>
            </button>
            {inputMode !== "free" ? (
              <button
                type="button"
                role="tab"
                aria-selected={planMode}
                className={`mob-mode-btn thr-planchip${planMode ? " mob-mode-btn-on thr-planchip-on" : ""}`}
                onClick={() => setPlanMode((current) => !current)}
                title={`Plan mode — ${bro.name} proposes before acting`}
              >
                <span className="mob-mode-icon"><GitBranch size={15} strokeWidth={2} /></span>
                <span className="mob-mode-label">Plan mode</span>
              </button>
            ) : null}
          </div>
        ) : null}
        {disabled ? (
          <div className="ob-composer-lock">
            <span className="ob-composer-lock-icon" aria-hidden="true">
              <WifiOff size={13} strokeWidth={2} />
            </span>
            <span className="ob-composer-lock-text">{disabledReason ? `Sending paused while ${disabledReason}` : "Sending paused — reconnect your computer to resume"}</span>
          </div>
        ) : null}
        <div className={`thr-composer-row${disabled ? " ob-composer-row-disabled" : ""}`} aria-disabled={disabled || undefined}>
          {inputMode === "free" && !disabled ? (
            <button type="button" className={`thr-free${connected ? "" : " thr-free-open"}`} aria-label={connected ? "Stop voice session" : `Wake up ${bro.name}`} disabled={loading} onClick={toggleVoice}>
              <span className="thr-free-led thr-free-led-active" />
              <span className="thr-free-label">{connected ? "Listening..." : "Hands-free · tap to talk"}</span>
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
                    if (event.key === "Tab" && event.shiftKey) {
                      event.preventDefault();
                      if (!disabled) setPlanMode((current) => !current);
                      return;
                    }
                    if (event.key === "Enter" && draft.trim()) {
                      event.preventDefault();
                      void submitDraftText();
                    }
                  }}
                  placeholder={disabled ? "Reconnect your computer before sending" : textState.enabled ? (planMode ? `Describe the task - ${bro.name} will plan it first` : `Message ${bro.name} - or hold the mic to talk`) : textState.reason}
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
  workspaceId,
  disabled,
  onTextTurn,
  onAudioTurn,
  onRemoveAudioTurn,
  onThreadResolved,
}: {
  bro: BroCardModel;
  selectedThreadId: string | null;
  createNewThread: boolean;
  workspaceId?: string | null;
  disabled: boolean;
  onTextTurn: (turn: TextTurn) => void;
  onAudioTurn: (turn: AudioTurn) => void;
  onRemoveAudioTurn: (turnId: string) => void;
  onThreadResolved: (threadId: string | null) => void;
}) {
  const shell = useNewbroShell();
  const [draft, setDraft] = useState("");
  const [planMode, setPlanMode] = useState(false);
  const [voiceMode, setVoiceMode] = useState<"ptt" | "free">("ptt");
  const [recording, setRecording] = useState(false);
  const [recSecs, setRecSecs] = useState(0);
  const recTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (recTimer.current) clearInterval(recTimer.current); }, []);
  const recFmt = `0:${String(recSecs).padStart(2, "0")}`;
  const hasText = draft.trim().length > 0;
  const opts = [
    {
      v: "ptt" as const,
      label: "Push to talk",
      icon: (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="11" rx="3"/>
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
        </svg>
      ),
    },
    {
      v: "free" as const,
      label: "Hands-free",
      icon: (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="10" y="4" width="4" height="9" rx="2"/>
          <path d="M6.5 8.5a6 6 0 0 0 0 7M17.5 8.5a6 6 0 0 1 0 7"/>
          <path d="M12 17v3"/>
        </svg>
      ),
    },
  ];
  const connected = shell.voiceSession.phase === "connected";
  const loading = shell.voiceSession.phase === "loading";
  const audioState = activeCodexAudioState(shell, bro);
  const textState = activeCodexTextState(shell, bro);
  const needsWorkspace = createNewThread && !workspaceId;
  const textDisabled = disabled || !textState.enabled || needsWorkspace;
  const micDisabled = disabled || !audioState.enabled || needsWorkspace;
  const recorder = usePushToTalkAudio({
    sessionId: shell.activeShellSessionId,
    broId: bro.id,
    targetThreadId: selectedThreadId,
    createNewThread,
    workspaceId,
    disabled: micDisabled,
    onTurn: onAudioTurn,
    onRemoveTurn: onRemoveAudioTurn,
    onError: shell.setShellError,
    onThreadResolved,
    onSent: shell.refreshShellSession,
  });

  // Sync local recording state with recorder phase (covers cancel/blur reset)
  useEffect(() => {
    if (recorder.phase !== "recording" && recording) {
      if (recTimer.current) clearInterval(recTimer.current);
      setRecording(false);
      setRecSecs(0);
    }
  }, [recorder.phase, recording]);

  const startRec = (e?: React.PointerEvent<HTMLButtonElement>) => {
    if (micDisabled) return;
    e?.preventDefault();
    if (e) e.currentTarget.setPointerCapture(e.pointerId);
    setRecording(true);
    setRecSecs(0);
    if (recTimer.current) clearInterval(recTimer.current);
    recTimer.current = setInterval(() => setRecSecs((s) => s + 1), 1000);
    void recorder.start();
  };
  const stopRec = () => {
    if (recTimer.current) clearInterval(recTimer.current);
    setRecording(false);
    setRecSecs(0);
    void recorder.stopAndSend();
  };
  const cancelRec = () => {
    if (recTimer.current) clearInterval(recTimer.current);
    setRecording(false);
    setRecSecs(0);
    recorder.cancel();
  };

  // Hold-Space push-to-talk: record while Space is held (when not typing), send on
  // release. Latest handlers/state live in refs so the window listener attaches once
  // and never runs against stale closures.
  const spaceHeldRef = useRef(false);
  const micDisabledRef = useRef(micDisabled);
  const voiceModeRef = useRef(voiceMode);
  const phaseRef = useRef(recorder.phase);
  const startRecRef = useRef(startRec);
  const stopRecRef = useRef(stopRec);
  const cancelRecRef = useRef(cancelRec);
  useEffect(() => {
    micDisabledRef.current = micDisabled;
    voiceModeRef.current = voiceMode;
    phaseRef.current = recorder.phase;
    startRecRef.current = startRec;
    stopRecRef.current = stopRec;
    cancelRecRef.current = cancelRec;
  });
  useEffect(() => {
    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.code === "Escape") { spaceHeldRef.current = false; return; }
      if (event.code !== "Space" || event.repeat) return;
      if (isEditableTarget(event.target)) return;
      if (voiceModeRef.current !== "ptt" || micDisabledRef.current) return;
      if (phaseRef.current !== "idle") return;
      event.preventDefault();
      spaceHeldRef.current = true;
      startRecRef.current();
    }
    function onKeyUp(event: KeyboardEvent) {
      if (event.code !== "Space" || !spaceHeldRef.current) return;
      event.preventDefault();
      spaceHeldRef.current = false;
      stopRecRef.current();
    }
    function onBlur() {
      if (!spaceHeldRef.current) return;
      spaceHeldRef.current = false;
      cancelRecRef.current();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  async function submitText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (needsWorkspace) {
      shell.setShellError("Choose a workspace before starting a new Codex thread.");
      return;
    }
    if (!text || textDisabled || !shell.activeShellSessionId) return;
    const turnId = `text-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const createdAt = new Date().toISOString();
    const startedAt = performance.now();
    directExecutorMetric("ui.text.submit.started", {
      client_request_id: turnId,
      session_id: shell.activeShellSessionId,
      bro_id: bro.id,
      target_thread_id: selectedThreadId,
      create_new_thread: createNewThread,
      text_length: text.length,
      plan_mode: planMode,
    });
    onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "sending", createdAt, planMode });
    directExecutorMetric("ui.text.local_turn_rendered", {
      client_request_id: turnId,
      elapsed_ms: Math.round(performance.now() - startedAt),
    });
    setDraft("");
    try {
      const response = await submitExecutorTextInstruction(shell.activeShellSessionId, {
        targetPersonaId: bro.id,
        targetThreadId: selectedThreadId,
        createNewThread,
        ...(workspaceId ? { workspaceId } : {}),
        clientRequestId: turnId,
        ...(planMode ? { planMode: true } : {}),
        text,
      });
      directExecutorMetric("ui.text.http.accepted", {
        client_request_id: turnId,
        instruction_id: response.instruction_id,
        target_thread_id: response.target_thread_id,
        elapsed_ms: Math.round(performance.now() - startedAt),
      });
      onThreadResolved(response.target_thread_id);
      onTextTurn({ id: turnId, broId: bro.id, threadId: response.target_thread_id ?? selectedThreadId, text, status: "sent", createdAt, planMode });
      await shell.refreshShellSession();
      directExecutorMetric("ui.text.refresh.completed", {
        client_request_id: turnId,
        instruction_id: response.instruction_id,
        elapsed_ms: Math.round(performance.now() - startedAt),
      });
    } catch (error: unknown) {
      const message = describeError(error, "Text could not be sent.");
      directExecutorMetric("ui.text.submit.failed", {
        client_request_id: turnId,
        elapsed_ms: Math.round(performance.now() - startedAt),
        error: message,
      });
      onTextTurn({ id: turnId, broId: bro.id, threadId: selectedThreadId, text, status: "failed", createdAt, error: message, planMode });
      shell.setShellError(message);
    }
  }

  const planChip = !disabled && (
    <button
      type="button"
      className={`dt-cmp-planchip${planMode ? " dt-cmp-planchip-on" : ""}`}
      onClick={() => setPlanMode((current) => !current)}
      aria-pressed={planMode}
      title={`Plan mode · Shift+Tab — ${bro.name} proposes a plan before acting`}
    >
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="9" width="6" height="6" rx="1.5"/>
        <rect x="15" y="4" width="6" height="6" rx="1.5"/>
        <rect x="15" y="14" width="6" height="6" rx="1.5"/>
        <path d="M9 12h3M12 7v10M12 7h3M12 17h3"/>
      </svg>
      <span className="dt-cmp-planchip-label">Plan{planMode ? " on" : ""}</span>
      <kbd className="dt-kbd dt-cmp-planchip-kbd">⇧⇥</kbd>
    </button>
  );

  return (
    <form className={`dt-cmp${disabled ? " dt-cmp-disabled" : ""}${planMode ? " dt-cmp-plan" : ""}`} onSubmit={submitText}>
      <div className="dt-cmp-head">
        <div className="dt-cmp-headl">
          <div className="dt-cmp-modewrap">
            <span className="dt-cmp-modewrap-label">Talk mode</span>
            <div className={`dt-cmp-modes${disabled ? " dt-cmp-modes-off" : ""}`} role="tablist" aria-label="How you talk to the bro">
              {opts.map((o) => {
                const on = voiceMode === o.v;
                return (
                  <button
                    key={o.v}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    disabled={disabled}
                    className={`dt-cmp-mode${on ? ` dt-cmp-mode-on dt-cmp-mode-on-${o.v}` : ""}`}
                    onClick={() => !disabled && setVoiceMode(o.v)}
                  >
                    <span className="dt-cmp-mode-ic" aria-hidden="true">{o.icon}</span>
                    <span>{o.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <span className="dt-cmp-hint">
          {disabled ? (
            <span>Sending paused — reconnect your computer to resume</span>
          ) : voiceMode === "ptt" ? (
            recording ? (
              <span>Recording… release the mic to send</span>
            ) : hasText ? (
              <span>Press <kbd className="dt-kbd">Enter</kbd> to send</span>
            ) : (
              <span>Hold <kbd className="dt-kbd">Space</kbd> to talk, or type your message</span>
            )
          ) : (
            <span>Mic's open — {bro.name} listens as you speak</span>
          )}
        </span>
      </div>
      <div className={`dt-cmp-bar${recording ? " dt-cmp-bar-rec" : ""}`}>
        {planChip}
        {recording ? (
          <div className="dt-cmp-rec">
            <span className="dt-cmp-rec-dot" aria-hidden="true" />
            <span className="dt-cmp-rec-label">Listening…</span>
            <span className="dt-cmp-rec-wave" aria-hidden="true">
              {Array.from({ length: 30 }).map((_, i) => {
                const h = 5 + Math.abs(Math.sin((i + 1) * 0.6)) * 15;
                return <i key={i} style={{ height: h, animationDelay: `${(i % 7) * 0.07}s` }} />;
              })}
            </span>
            <span className="dt-cmp-rec-time">{recFmt}</span>
            <span className="dt-cmp-rec-hint">release to send</span>
          </div>
        ) : (
          <>
            <label className="sr-only" htmlFor={`message-${bro.id}`}>Message</label>
            <input
              id={`message-${bro.id}`}
              className="dt-cmp-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Tab" && event.shiftKey) {
                  event.preventDefault();
                  if (!disabled) setPlanMode((current) => !current);
                }
              }}
              placeholder={disabled ? "Reconnect your computer before sending" : textState.enabled ? (planMode ? `Describe the task — ${bro.name} will plan it first...` : `Type to ${bro.name}...`) : textState.reason}
              disabled={disabled}
            />
          </>
        )}
        {hasText && !recording ? (
          <button
            type="submit"
            className="dt-cmp-action dt-cmp-action-send dt-cmp-send"
            aria-label={textDisabled ? textState.reason : "Send message"}
            disabled={textDisabled || !draft.trim()}
          >
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7"/>
            </svg>
          </button>
        ) : (
          <button
            type="button"
            data-testid="voice-session-start"
            className={`dt-cmp-action dt-cmp-action-mic dt-cmp-mic dt-cmp-mic-${micDisabled ? "off" : recorder.phase === "recording" ? "free" : "ptt"}${recording ? " dt-cmp-action-rec" : micDisabled ? " dt-cmp-action-mic-off" : " dt-cmp-action-mic-on"}`}
            aria-label={micDisabled ? audioState.reason : "Hold to record audio"}
            title={micDisabled ? audioState.reason : "Hold to record audio"}
            disabled={micDisabled || loading || recorder.phase === "sending"}
            onPointerDown={startRec}
            onPointerUp={() => stopRec()}
            onPointerLeave={recording ? cancelRec : undefined}
            onPointerCancel={cancelRec}
            onBlur={cancelRec}
            onKeyDown={(event) => {
              if ((event.key === " " || event.key === "Enter") && recorder.phase === "idle") {
                startRec();
              }
            }}
            onKeyUp={(event) => {
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                stopRec();
              }
            }}
          >
            {recording ? (
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
                <rect x="6" y="6" width="12" height="12" rx="3"/>
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="9" y="3" width="6" height="12" rx="3"/>
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>
                {micDisabled && <path d="M3 3l18 18"/>}
              </svg>
            )}
          </button>
        )}
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
  pendingWorkspaceId,
  hasMore,
  showMoreLabel,
  onSelectThread,
  onNewThread,
  onShowMore,
}: {
  bro: BroCardModel;
  threads: BroThreadRecord[];
  totalThreadCount: number;
  selectedThreadId: string | null;
  pendingNewThread: boolean;
  pendingWorkspaceId: string | null;
  hasMore?: boolean;
  showMoreLabel?: string;
  onSelectThread: (threadId: string) => void;
  onNewThread: () => void;
  onShowMore: () => void;
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
                    <span>{pendingWorkspaceId ? workspaceNameFromId(pendingWorkspaceId) : "created on first send"}</span>
                  </span>
                </span>
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
                    {thread.workspaceName ? (
                      <>
                        <span className="dt-bro-meta-sep">·</span>
                        <span>{thread.workspaceName}</span>
                      </>
                    ) : null}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {(hasMore ?? hiddenThreadCount > 0) ? (
          <button type="button" className="dt-thread-more" onClick={onShowMore}>
            <Layers size={12} strokeWidth={2.2} aria-hidden="true" />
            <span>{showMoreLabel ?? `Show ${Math.min(THREAD_LIST_PAGE_SIZE, hiddenThreadCount)} more`}</span>
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
  const [threadVisibleCount, setThreadVisibleCount] = useState(THREAD_LIST_PAGE_SIZE);
  const [connectOpen, setConnectOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const threadScrollRef = useRef<HTMLDivElement | null>(null);
  const bro = shell.bros.find((candidate) => candidate.id === broId) ?? null;
  const nodeState = deriveBroNodeState(bro, shell.executorNodes);
  const needsConnect = bro?.source === "runtime"
    && nodeStateNeedsConnect(nodeState)
    && nodeState.kind !== "never_connected";
  const offline = nodeState.kind === "usable_disconnected" || nodeState.kind === "never_connected"
    ? nodeState.node
    : null;
  const persona = bro?.source === "runtime" ? shell.runtimePersonas.find((item) => item.persona_id === bro.id) ?? null : null;
  const threads = bro?.source === "runtime" ? buildBroThreadRecords(bro.id, shell.broThreads) : [];
  const workspaceOptions = useMemo(() => buildWorkspaceOptions(threads), [threads]);
  const {
    selectedThreadId,
    pendingNewThread,
    pendingWorkspaceId,
    workspacePickerOpen,
    setWorkspacePickerOpen,
    selectedThread,
    activeThreadId,
    selectThread,
    newThread,
    selectWorkspace,
    resolveThread,
  } = useThreadSelection({
    broId: bro?.id ?? null,
    broSource: bro?.source ?? null,
    threads,
    workspaceOptions,
    needsConnect,
    openThread: (id, tid) => { void shell.openRuntimeBroThread(id, tid); },
    closeThread: (id, tid) => { void shell.closeRuntimeBroThread(id, tid); },
    onNoWorkspace: () => shell.setShellError("No Codex workspace is available for this Bro yet."),
  });
  const visibleThreads = useMemo(
    () => threads.slice(0, threadVisibleCount),
    [threadVisibleCount, threads],
  );
  const broThreadPage = bro?.source === "runtime" ? shell.broThreadPages[bro.id] : null;
  const hasMoreRuntimeThreads = Boolean(broThreadPage?.has_more && broThreadPage.next_cursor);
  const hiddenThreadCount = Math.max(0, threads.length - visibleThreads.length);
  const hasMoreThreads = hasMoreRuntimeThreads || hiddenThreadCount > 0;
  const showMoreLabel = hasMoreRuntimeThreads
    ? "Show more"
    : `Show ${Math.min(THREAD_LIST_PAGE_SIZE, hiddenThreadCount)} more`;
  const threadScrollVersion = [
    activeThreadId ?? "new",
    shell.broTimelineTurns
      .filter((turn) => timelineTurnMatchesThread(turn, broId, activeThreadId))
      .map((turn) => `${turn.turn_id}:${turn.status}:${turn.updated_at ?? ""}:${turn.assistant?.text ?? ""}`)
      .join("|"),
    shell.interactionRequests
      .filter((request) => planProposalRequestMatchesThread(request, broId, activeThreadId, shell.broTimelineTurns))
      .map((request) => `${request.request_id}:${request.status}`)
      .join("|"),
    textTurns.filter((turn) => turn.broId === broId && turnMatchesThread(turn, activeThreadId)).map((turn) => `${turn.id}:${turn.status}`).join("|"),
    audioTurns.filter((turn) => turn.broId === broId && turnMatchesThread(turn, activeThreadId)).map((turn) => `${turn.id}:${turn.status}:${turn.transcript ?? ""}`).join("|"),
  ].join("::");

  useEffect(() => {
    setThreadVisibleCount(THREAD_LIST_PAGE_SIZE);
  }, [broId]);

  useEffect(() => {
    if (!activeThreadId) return;
    const selectedIndex = threads.findIndex((thread) => thread.threadId === activeThreadId);
    if (selectedIndex < threadVisibleCount) return;
    setThreadVisibleCount(Math.ceil((selectedIndex + 1) / THREAD_LIST_PAGE_SIZE) * THREAD_LIST_PAGE_SIZE);
  }, [activeThreadId, threadVisibleCount, threads]);

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
  if (!bro) return null;

  const disabledReason = offline ? `${bro.executorType ?? offline.name} is not connected.` : null;
  const visibleTextTurns = textTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleAudioTurns = audioTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleTimelineTurns = shell.broTimelineTurns.filter(
    (turn) => timelineTurnMatchesThread(turn, bro.id, activeThreadId),
  );
  const directThreadIntent = {
    targetThreadId: activeThreadId,
    createNewThread: activeThreadId === null,
    workspaceId: activeThreadId === null ? pendingWorkspaceId : null,
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
    <DesktopFrame active="detail" bro={bro} onHome={onHome} onConnect={() => setConnectOpen(true)}>
      {needsConnect && shell.activeShellSessionId ? (
        <div className="dt-main-pad nb-detail-connect-stage">
          <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onHome} onCreated={shell.refreshShellSession} bro={bro} mode={nodeState.kind === "never_connected" ? "setup" : undefined} />
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
            pendingWorkspaceId={pendingWorkspaceId}
            hasMore={hasMoreThreads}
            showMoreLabel={showMoreLabel}
            onSelectThread={selectThread}
            onNewThread={newThread}
            onShowMore={() => {
              if (bro.source === "runtime" && hasMoreRuntimeThreads) {
                setThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE);
                void shell.loadMoreBroThreads(bro.id);
                return;
              }
              setThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE);
            }}
          />
          <section className="dt-pane">
            {bro.source === "runtime" ? (
              <div className="nb-detail-edit-row">
                <button type="button" className="nb-bro-edit-button" aria-label="Edit Bro" onClick={() => setRenameOpen(true)}>
                  <Pencil size={14} strokeWidth={2.1} aria-hidden="true" />
                </button>
              </div>
            ) : null}
            {offline ? (
              <div className="dt-pane-banner">
                <OfflineBanner bro={bro} node={offline} neverConnected={nodeState.kind === "never_connected"} onConnect={() => setConnectOpen(true)} />
              </div>
            ) : null}
            <div className="dt-pane-scroll" ref={threadScrollRef}>
              <div
                className="dt-pane-content"
                aria-live="polite"
                aria-relevant="additions"
                aria-busy={shell.openingThreadId ? true : undefined}
              >
                <ThreadPanel
                  bro={bro}
                  textTurns={visibleTextTurns}
                  audioTurns={visibleAudioTurns}
                  timelineTurns={visibleTimelineTurns}
                  selectedThread={selectedThread}
                  onTextTurn={upsertTextTurn}
                  disabled={Boolean(offline)}
                  disabledReason={disabledReason}
                  hasOlderTimeline={Boolean(activeThreadId && shell.broTimelinePages[activeThreadId]?.has_more)}
                  onLoadOlderTimeline={() => {
                    if (activeThreadId) void shell.loadMoreBroTimeline(bro.id, activeThreadId);
                  }}
                />
              </div>
            </div>
            <DesktopComposerBar
              bro={bro}
              selectedThreadId={directThreadIntent.targetThreadId}
              createNewThread={directThreadIntent.createNewThread}
              workspaceId={directThreadIntent.workspaceId}
              disabled={Boolean(offline)}
              onTextTurn={upsertTextTurn}
              onAudioTurn={upsertAudioTurn}
              onRemoveAudioTurn={removeAudioTurn}
              onThreadResolved={resolveThread}
            />
          </section>
        </div>
      ) : null}
      <WorkspacePickerDialog
        open={workspacePickerOpen}
        broName={bro.name}
        workspaceOptions={workspaceOptions}
        onSelectWorkspace={selectWorkspace}
        onClose={() => setWorkspacePickerOpen(false)}
      />
      {connectOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setConnectOpen(false)} onCreated={shell.refreshShellSession} bro={bro} mode={nodeState.kind === "never_connected" ? "setup" : undefined} />
      ) : null}
      {renameOpen && shell.activeShellSessionId && bro.source === "runtime" ? (
        <RenameBroDialog sessionId={shell.activeShellSessionId} bro={bro} onClose={() => setRenameOpen(false)} onRenamed={shell.refreshShellSession} />
      ) : null}
    </DesktopFrame>
  );
}

function MobileBroCard({ bro, onOpen, onSetup }: { bro: BroCardModel; onOpen: (id: string) => void; onSetup: (bro: BroCardModel) => void }) {
  const state = homeBroState(bro);
  const tone = homeBroTone(state);
  const chipLabel = homeBroChipLabel(state);
  if (state === "working") {
    return (
      <button type="button" data-testid={`mobile-bro-row-${bro.id}`} className={`home-card home-card-${tone}`} onClick={() => onOpen(bro.id)}>
        <div className="home-card-head">
          <div className={`home-card-avatar home-card-avatar-${tone}`}>
            <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={48} />
          </div>
          <div className="home-card-headtext">
            <div className="home-card-name">
              {bro.name}
              {bro.executorType && <span className="home-card-role">· on {bro.executorType}</span>}
            </div>
            <div className="home-card-meta">
              <span className={`home-chip home-chip-${tone}`}><span className="home-chip-dot" />{chipLabel}</span>
            </div>
          </div>
          <span className="home-card-arrow">›</span>
        </div>
        <div className="home-card-task home-card-task-running">
          <span className="home-card-spin" aria-hidden="true" />
          <span className="home-card-task-text">{bro.taskTitle}</span>
        </div>
      </button>
    );
  }
  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`mobile-bro-row-${bro.id}`}
      className="home-row"
      onClick={() => onOpen(bro.id)}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(bro.id); } }}
    >
      <div className={`home-row-avatar home-row-avatar-${tone}`}>
        <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={42} />
      </div>
      <div className="home-row-body">
        <div className="home-row-top">
          <span className="home-row-name">{bro.name}</span>
          {bro.executorType && <span className="home-row-role">· on {bro.executorType}</span>}
        </div>
        <div className="home-row-task">{homeBroLast(bro, state)}</div>
      </div>
      <div className="home-row-right">
        <span className={`home-chip home-chip-${tone}`}><span className="home-chip-dot" />{chipLabel}</span>
        <HomeBroConnectAction bro={bro} variant="card" onSetup={onSetup} />
      </div>
    </div>
  );
}

function HomeBroEditable({
  bro,
  featured,
  editing,
  onRemove,
  onRename,
  onOpen,
  onSetup,
}: {
  bro: BroCardModel;
  featured: boolean;
  editing: boolean;
  onRemove: (id: string) => void;
  onRename: (bro: BroCardModel) => void;
  onOpen: (id: string) => void;
  onSetup: (bro: BroCardModel) => void;
}) {
  return (
    <div className={`home-edit-wrap${editing ? " home-edit-wrap-on" : ""}${featured ? " home-edit-wrap-card" : " home-edit-wrap-row"}`}>
      <MobileBroCard bro={bro} onOpen={editing ? () => {} : onOpen} onSetup={onSetup} />
      {editing && (
        <div className="home-edit-actions">
          <button
            type="button"
            className="home-edit-rename"
            aria-label={`Rename ${bro.name}`}
            onClick={(e) => { e.stopPropagation(); onRename(bro); }}
          >
            <Pencil size={12} strokeWidth={2.4} />
          </button>
          <button
            type="button"
            className="home-edit-remove"
            aria-label={`Remove ${bro.name}`}
            onClick={(e) => { e.stopPropagation(); onRemove(bro.id); }}
          >
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
              <path d="M6 12h12" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}

function AddBroTile({ editing, onClick }: { editing: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`home-add-row${editing ? " home-add-row-on" : ""}`} onClick={onClick}>
      <span className="home-add-icon">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </span>
      <span className="home-add-body">
        <span className="home-add-title">Add a bro</span>
        <span className="home-add-sub">Download the app + connect a computer</span>
      </span>
      <span className="home-add-arrow">›</span>
    </button>
  );
}

function HomeAccountSheet({
  account,
  onClose,
  onEnterEdit,
  onAddBro,
  onSignOut,
  signOutPending,
}: {
  account: string;
  onClose: () => void;
  onEnterEdit: () => void;
  onAddBro: () => void;
  onSignOut: () => void;
  signOutPending: boolean;
}) {
  const initial = account.trim().charAt(0).toUpperCase() || "N";
  return (
    <section className="acct-sheet" role="dialog" aria-label="Account">
      <div className="acct-sheet-handle" aria-hidden="true" />
      <header className="acct-identity">
        <div className="acct-identity-avatar"><span>{initial}</span></div>
        <div className="acct-identity-body">
          <div className="acct-identity-name">{account}</div>
          <div className="acct-identity-mail">{account}</div>
        </div>
        <button type="button" className="acct-identity-edit" aria-label="Close" onClick={onClose}>
          <X size={15} strokeWidth={2} />
        </button>
      </header>

      <div className="acct-section">
        <div className="acct-section-eyebrow">BROS</div>
        <button type="button" className="acct-row" onClick={onAddBro}>
          <span className="acct-row-glyph acct-row-glyph-coral">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Add a bro</span>
            <span className="acct-row-meta">Name it, then connect a computer</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row" onClick={onEnterEdit}>
          <span className="acct-row-glyph">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 6h13M3 12h10M3 18h7" /><path d="M19 14l3 3-3 3M22 17h-5" />
            </svg>
          </span>
          <span className="acct-row-body">
            <span className="acct-row-title">Manage bros</span>
            <span className="acct-row-meta">Rename or remove</span>
          </span>
          <span className="acct-row-chev">›</span>
        </button>
      </div>

      <div className="acct-section">
        <div className="acct-section-eyebrow">DEVICES</div>
        <p className="acct-row-meta">Pair a Cardputer or other device using the code shown on its screen.</p>
        <DevicePairingForm onClaim={claimDevice} />
      </div>

      <div className="acct-section">
        <div className="acct-section-eyebrow">APP</div>
        <button type="button" className="acct-row acct-row-compact">
          <span className="acct-row-title">Notifications</span>
          <span className="acct-row-chev">›</span>
        </button>
        <button type="button" className="acct-row acct-row-compact">
          <span className="acct-row-title">Help &amp; feedback</span>
          <span className="acct-row-chev">›</span>
        </button>
      </div>

      <div className="acct-foot">
        <button
          type="button"
          className={`acct-signout${signOutPending ? " acct-signout-pending" : ""}`}
          onClick={onSignOut}
          disabled={signOutPending}
        >
          {signOutPending ? (
            <>
              <span className="acct-signout-spin" aria-hidden="true" />
              <span>Signing out…</span>
            </>
          ) : (
            <>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <path d="M16 17l5-5-5-5" /><path d="M21 12H9" />
              </svg>
              <span>Sign out</span>
            </>
          )}
        </button>
        <div className="acct-version">Newbro · workspace</div>
      </div>
    </section>
  );
}

function HomeConfirmRemove({
  bro,
  sessionId,
  onCancel,
  onConfirmed,
}: {
  bro: BroCardModel;
  sessionId: string;
  onCancel: () => void;
  onConfirmed: () => void;
}) {
  const [pending, setPending] = useState(false);
  const confirm = async () => {
    setPending(true);
    try {
      await deletePersona(sessionId, bro.id);
      onConfirmed();
    } finally {
      setPending(false);
    }
  };
  const sessionWarning = homeBroState(bro) === "working";
  return (
    <section className="acct-confirm" role="alertdialog" aria-label={`Remove ${bro.name}`}>
      <div className="acct-confirm-card">
        <div className="acct-confirm-head">
          <div className="acct-confirm-title">Remove {bro.name}?</div>
          <div className="acct-confirm-sub">
            {sessionWarning
              ? `${bro.name} is mid-task. The session ends, the draft is kept, and the executor disconnects.`
              : `${bro.name} disconnects from their node and stops appearing in your workspace. Their threads stay.`}
          </div>
        </div>
        <div className="acct-confirm-actions">
          <button type="button" className="acct-confirm-danger" onClick={confirm} disabled={pending}>
            {pending ? "Removing…" : sessionWarning ? "Stop & remove" : "Remove from workspace"}
          </button>
        </div>
      </div>
      <button type="button" className="acct-confirm-cancel" onClick={onCancel}>Cancel</button>
    </section>
  );
}



function MobileStage({ children }: { children: React.ReactNode }) {
  return (
    <div className="nb-mobile-stage" data-testid="mobile-walkie">
      <div className="nb-mobile-phone">
        {children}
      </div>
    </div>
  );
}

function MobileHome({ onOpenBro }: { onOpenBro: (id: string, threadId?: string) => void }) {
  const shell = useNewbroShell();
  const [accountOpen, setAccountOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [signOutPending, setSignOutPending] = useState(false);
  const [setupBro, setSetupBro] = useState<BroCardModel | null>(null);
  const [renameBro, setRenameBro] = useState<BroCardModel | null>(null);

  const homeBros = useMemo(() => [...shell.bros].sort(compareHomeBros), [shell.bros]);
  const working = homeBros.filter((bro) => homeBroState(bro) === "working");
  const standing = homeBros.filter((bro) => homeBroState(bro) !== "working");
  const recents = buildHomeRecents(shell.broThreads, shell.runtimePersonas);
  const anyOverlay = accountOpen || addOpen || !!confirmId || !!renameBro;
  const confirmBro = confirmId ? shell.bros.find((b) => b.id === confirmId) ?? null : null;
  const account = shell.currentUser?.email ?? shell.currentUser?.user_id ?? "Signed in";

  const closeAll = () => { setAccountOpen(false); setAddOpen(false); setConfirmId(null); setRenameBro(null); };
  const enterEdit = () => { setAccountOpen(false); setEditMode(true); };

  const handleSignOut = () => {
    setSignOutPending(true);
    void shell.logout().finally(() => setSignOutPending(false));
  };

  if (!shell.hasLoadedShellSnapshot) return null;
  return (
    <MobileStage>
      <div
        className={`home nb-mobile-home${shell.runtimePersonas.length === 0 ? " ob-firsthome" : ""}${editMode ? " home-editing" : ""}${anyOverlay ? " home-dimmed" : ""}`}
        data-testid="mobile-home"
      >
        <header className="home-bar">
          {editMode ? (
            <>
              <div className="home-bar-l home-bar-l-edit">
                <div className="home-bar-titles">
                  <div className="home-bar-greet">Edit bros</div>
                  <div className="home-bar-meta">Rename or remove</div>
                </div>
              </div>
              <button type="button" className="home-bar-done" onClick={() => setEditMode(false)}>Done</button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="home-bar-l home-bar-l-tap"
                aria-label="Open account"
                onClick={() => setAccountOpen(true)}
              >
                <div className="home-bar-logo"><img src="/newbro.webp" alt="" draggable={false} /></div>
                <div className="home-bar-titles">
                  <div className="home-bar-greet">Hi · workspace</div>
                  <div className="home-bar-meta">
                    {shell.runtimePersonas.length === 0
                      ? "workspace is empty · let's fix that"
                      : `${working.length} of ${shell.bros.length} bros working · ${recents.length} sessions`}
                  </div>
                </div>
              </button>
              <button type="button" className="home-bar-btn" aria-label="Account" onClick={() => setAccountOpen(true)}>
                <Settings size={19} strokeWidth={1.9} />
              </button>
            </>
          )}
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
                  <p className="ob-hero-sub">
                    A <strong>bro</strong> is a teammate that works on a computer
                    you trust. Give it a name, connect a computer, and it&rsquo;ll show
                    up here ready to go.
                  </p>
                  <div className="ob-hero-actions">
                    <button type="button" className="ob-cta ob-cta-block" onClick={() => setAddOpen(true)}>
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
              {working.length > 0 && (
                <section className="home-section">
                  <div className="home-section-head">
                    <span className="home-section-eyebrow">In flight · {working.length}</span>
                    <span className="home-section-sub">{editMode ? "Removing stops the task" : "Sessions currently dispatched"}</span>
                  </div>
                  <div className="home-flight">
                    {working.map((bro) => (
                      <HomeBroEditable key={bro.id} bro={bro} featured editing={editMode} onRemove={setConfirmId} onRename={setRenameBro} onOpen={onOpenBro} onSetup={setSetupBro} />
                    ))}
                  </div>
                </section>
              )}
              <section className="home-section">
                <div className="home-section-head">
                  <span className="home-section-eyebrow">Standing by · {standing.length}</span>
                  {!editMode && <span className="home-section-sub">Idle, paused, or offline</span>}
                </div>
                <div className="home-list">
                  {standing.map((bro) => (
                    <HomeBroEditable key={bro.id} bro={bro} featured={false} editing={editMode} onRemove={setConfirmId} onRename={setRenameBro} onOpen={onOpenBro} onSetup={setSetupBro} />
                  ))}
                  <AddBroTile editing={editMode} onClick={() => setAddOpen(true)} />
                </div>
              </section>
            </>
          )}
          {!editMode && recents.length > 0 && (
            <section className="home-section">
              <div className="home-section-head"><span className="home-section-eyebrow">Recent · {recents.length}</span></div>
              <ul className="home-recents">
                {recents.map((recent) => (
                  <li key={recent.id}>
                    <button type="button" className="home-recent" onClick={() => onOpenBro(recent.broId, recent.threadId)}>
                      <span className="home-recent-icon"><FileText size={13} /></span>
                      <span className="home-recent-body">
                        <span className="home-recent-title">{recent.title}</span>
                        <span className="home-recent-meta">{recent.bro} · {recent.when}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </main>
        {anyOverlay && <div className="home-scrim" onClick={closeAll} aria-hidden="true" />}
        {accountOpen && (
          <HomeAccountSheet
            account={account}
            onClose={() => setAccountOpen(false)}
            onEnterEdit={enterEdit}
            onAddBro={() => { setAccountOpen(false); setAddOpen(true); }}
            onSignOut={handleSignOut}
            signOutPending={signOutPending}
          />
        )}
        {confirmBro && shell.activeShellSessionId && (
          <HomeConfirmRemove
            bro={confirmBro}
            sessionId={shell.activeShellSessionId}
            onCancel={() => setConfirmId(null)}
            onConfirmed={() => { setConfirmId(null); void shell.refreshShellSession(); }}
          />
        )}
        {renameBro && shell.activeShellSessionId ? (
          <RenameBroDialog
            bro={renameBro}
            sessionId={shell.activeShellSessionId}
            onClose={() => setRenameBro(null)}
            onRenamed={shell.refreshShellSession}
            mobile
          />
        ) : null}
      </div>
      {addOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet
          sessionId={shell.activeShellSessionId}
          onClose={() => setAddOpen(false)}
          onCreated={shell.refreshShellSession}
          mobile
        />
      ) : null}
      {setupBro && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setSetupBro(null)} onCreated={shell.refreshShellSession} bro={setupBro} mobile />
      ) : null}
    </MobileStage>
  );
}

function MobileDetail({ bro, onBack }: { bro: BroCardModel; onBack: () => void }) {
  const shell = useNewbroShell();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [textTurns, setTextTurns] = useState<TextTurn[]>([]);
  const [audioTurns, setAudioTurns] = useState<AudioTurn[]>([]);
  const [drawerThreadVisibleCount, setDrawerThreadVisibleCount] = useState(THREAD_LIST_PAGE_SIZE);
  const [connectOpen, setConnectOpen] = useState(false);
  const nodeState = deriveBroNodeState(bro, shell.executorNodes);
  const offline = nodeState.kind === "usable_disconnected" ? nodeState.node : null;
  const needsConnect = bro.source === "runtime" && nodeStateNeedsConnect(nodeState) && nodeState.kind !== "no_bound_node";
  const persona = bro.source === "runtime" ? shell.runtimePersonas.find((item) => item.persona_id === bro.id) ?? null : null;
  const threads = bro.source === "runtime" ? buildBroThreadRecords(bro.id, shell.broThreads) : [];
  const workspaceOptions = useMemo(() => buildWorkspaceOptions(threads), [threads]);
  const {
    selectedThreadId,
    pendingNewThread,
    pendingWorkspaceId,
    workspacePickerOpen,
    setWorkspacePickerOpen,
    selectedThread,
    activeThreadId,
    selectThread,
    newThread,
    selectWorkspace,
    resolveThread,
  } = useThreadSelection({
    broId: bro?.id ?? null,
    broSource: bro?.source ?? null,
    threads,
    workspaceOptions,
    needsConnect,
    openThread: (id, tid) => { void shell.openRuntimeBroThread(id, tid); },
    closeThread: (id, tid) => { void shell.closeRuntimeBroThread(id, tid); },
    onNoWorkspace: () => shell.setShellError("No Codex workspace is available for this Bro yet."),
  });
  const visibleDrawerThreads = useMemo(
    () => threads.slice(0, drawerThreadVisibleCount),
    [drawerThreadVisibleCount, threads],
  );
  const hiddenDrawerThreadCount = Math.max(0, threads.length - visibleDrawerThreads.length);
  const drawerThreadPage = bro.source === "runtime" ? shell.broThreadPages[bro.id] : null;
  const hasMoreRuntimeDrawerThreads = Boolean(drawerThreadPage?.has_more && drawerThreadPage.next_cursor);
  const hasMoreDrawerThreads = hasMoreRuntimeDrawerThreads || hiddenDrawerThreadCount > 0;
  const drawerShowMoreLabel = hasMoreRuntimeDrawerThreads
    ? "Show more"
    : `Show ${Math.min(THREAD_LIST_PAGE_SIZE, hiddenDrawerThreadCount)} more`;
  const headerThreadTitle = pendingNewThread
    ? "New thread"
    : selectedThread?.title ?? (bro.status === "busy" ? bro.taskTitle : "New thread");
  const visibleTextTurns = textTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleAudioTurns = audioTurns.filter((turn) => turn.broId === bro.id && turnMatchesThread(turn, activeThreadId));
  const visibleTimelineTurns = shell.broTimelineTurns.filter(
    (turn) => timelineTurnMatchesThread(turn, bro.id, activeThreadId),
  );
  const directThreadIntent = {
    targetThreadId: activeThreadId,
    createNewThread: activeThreadId === null,
    workspaceId: activeThreadId === null ? pendingWorkspaceId : null,
  };
  useEffect(() => {
    setAudioTurns((current) => applyAudioTranscripts(current, shell.executionRuns));
  }, [shell.executionRuns]);
  useEffect(() => {
    setDrawerThreadVisibleCount(THREAD_LIST_PAGE_SIZE);
  }, [bro.id]);
  useEffect(() => {
    if (!activeThreadId) return;
    const selectedIndex = threads.findIndex((thread) => thread.threadId === activeThreadId);
    if (selectedIndex < drawerThreadVisibleCount) return;
    setDrawerThreadVisibleCount(Math.ceil((selectedIndex + 1) / THREAD_LIST_PAGE_SIZE) * THREAD_LIST_PAGE_SIZE);
  }, [activeThreadId, drawerThreadVisibleCount, threads]);
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
              <p>Create or reveal Install + connect and run it on the computer where this Bro should work.</p>
              <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={onBack} onCreated={shell.refreshShellSession} bro={bro} mode={nodeState.kind === "never_connected" ? "setup" : undefined} mobile />
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
            </div>
            <div className="thr-bar-meta">
              <div className="thr-bar-title-row">
                <span className="thr-bar-name">{bro.name}</span>
                <span className="thr-bar-sep">·</span>
                <span className="thr-bar-thread-title">{headerThreadTitle}</span>
              </div>
              <div className={`thr-bar-state thr-bar-state-${offline ? "warn" : "live"}`}>
                <span className="thr-bar-dot" />
                {offline ? `Offline · ${bro.executorType ?? offline.name}` : "Live · ready"}
              </div>
            </div>
          </div>

          <button type="button" className="thr-more" aria-label="Switch thread" disabled={Boolean(offline)} onClick={() => setPickerOpen(true)}>
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
                      <span className="thr-drawer-item-when">
                        {pendingWorkspaceId ? workspaceNameFromId(pendingWorkspaceId) : "first send"}
                      </span>
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
                  onClick={() => { selectThread(thread.threadId); setPickerOpen(false); }}
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
                    {thread.workspaceName ? (
                      <>
                        <span className="thr-drawer-item-sep">·</span>
                        <span className="thr-drawer-item-when">{thread.workspaceName}</span>
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
          {hasMoreDrawerThreads ? (
            <button
              type="button"
              className="thr-drawer-more"
              onClick={() => {
                if (bro.source === "runtime" && hasMoreRuntimeDrawerThreads) {
                  setDrawerThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE);
                  void shell.loadMoreBroThreads(bro.id);
                  return;
                }
                setDrawerThreadVisibleCount((count) => count + THREAD_LIST_PAGE_SIZE);
              }}
            >
              <Layers size={14} strokeWidth={2.2} />
              <span>{drawerShowMoreLabel}</span>
            </button>
          ) : null}
          <button type="button" className="thr-drawer-new" onClick={() => { newThread(); setPickerOpen(false); }}>
            <Plus size={14} strokeWidth={2.2} />
            <span>New thread with {bro.name}</span>
          </button>
        </aside>
        {offline ? <OfflineBanner bro={bro} node={offline} neverConnected={nodeState.kind === "never_connected"} onConnect={() => setConnectOpen(true)} mobile /> : null}
        <MobileThreadSurface
          bro={bro}
          selectedThreadId={directThreadIntent.targetThreadId}
          selectedThread={selectedThread}
          createNewThread={directThreadIntent.createNewThread}
          workspaceId={directThreadIntent.workspaceId}
          textTurns={visibleTextTurns}
          audioTurns={visibleAudioTurns}
          timelineTurns={visibleTimelineTurns}
          onTextTurn={upsertTextTurn}
          onAudioTurn={upsertAudioTurn}
          onRemoveAudioTurn={removeAudioTurn}
          onThreadResolved={resolveThread}
          disabled={Boolean(offline)}
          disabledReason={offline ? `${bro.executorType ?? offline.name} is not connected.` : null}
        />
        <WorkspacePickerDialog
          open={workspacePickerOpen}
          broName={bro.name}
          workspaceOptions={workspaceOptions}
          onSelectWorkspace={(workspaceId) => { selectWorkspace(workspaceId); setPickerOpen(false); }}
          onClose={() => setWorkspacePickerOpen(false)}
        />
      </div>
      {connectOpen && shell.activeShellSessionId ? (
        <CreateConnectSheet sessionId={shell.activeShellSessionId} onClose={() => setConnectOpen(false)} onCreated={shell.refreshShellSession} bro={bro} mode={nodeState.kind === "never_connected" ? "setup" : undefined} mobile />
      ) : null}
    </MobileStage>
  );
}

export function ArtboardHomePage({ onOpenBro }: { onOpenBro: (broId: string, threadId?: string) => void }) {
  return <DesktopHome onOpenBro={onOpenBro} />;
}

export function ArtboardBroDetailPage({ broId, onHome }: { broId: string; onHome: () => void }) {
  return <DesktopDetail broId={broId} onHome={onHome} />;
}

export function ArtboardMobilePage({
  broId,
  onOpenBro,
  onBack,
}: {
  broId?: string | null;
  onOpenBro?: (id: string, threadId?: string) => void;
  onBack?: () => void;
} = {}) {
  const shell = useNewbroShell();
  const detailBro = broId ? shell.bros.find((bro) => bro.id === broId) ?? null : null;
  if (broId && !shell.hasLoadedShellSnapshot) return null;
  if (detailBro) return <MobileDetail bro={detailBro} onBack={onBack ?? (() => undefined)} />;
  if (broId) return null;
  return <MobileHome onOpenBro={onOpenBro ?? (() => undefined)} />;
}

export function buildRuntimeBroCards(
  personas: Persona[],
  nodes: ExecutorNodeRecord[],
  shell: Pick<ReturnType<typeof useNewbroShell>, "executionRuns" | "taskSummaries" | "tasks" | "recentExecutionDetails">,
) {
  return buildBroCardModels(personas, nodes, shell.executionRuns, shell.taskSummaries, shell.tasks, shell.recentExecutionDetails);
}
