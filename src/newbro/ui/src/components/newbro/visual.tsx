import { ArrowLeft, Bot, CheckCircle2, Clock, FileText, Mic, PencilLine, Play, SendHorizontal, Trash2 } from "lucide-react";
import type { CSSProperties, KeyboardEventHandler, PointerEventHandler, ReactNode } from "react";
import type { AgentEvent, TaskSummary } from "../../types";
import { MarkdownText } from "../ui/markdown-text";
import { BroPortrait } from "./BroPortrait";
import type { BroCardModel, BroTaskRecord } from "./types";

export function WindowDots() {
  return null;
}

export function NewbroLogo() {
  return (
    <div className="flex items-center gap-2 px-1">
      <div className="flex items-center gap-2">
        <div className="grid h-[34px] w-[34px] shrink-0 place-items-center overflow-hidden rounded-[10px] border border-[#e5e7eb] bg-white shadow-[0_2px_8px_rgba(0,0,0,0.1)]" aria-hidden="true">
          <img src="/newbro.webp" alt="" className="h-full w-full scale-[1.18] object-cover" />
        </div>
        <div>
          <div className="text-[14px] font-bold uppercase tracking-[0.08em] text-[#111827]">NEWBRO</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-[#9ca3af]">Voice Command</div>
        </div>
      </div>
    </div>
  );
}

export function VoicePad({
  active,
  disabled,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
  onKeyDown,
  onKeyUp,
  onBlur,
  label = "Hold to Talk",
  statusLabel = "I'm listening",
}: {
  active: boolean;
  disabled?: boolean;
  onPointerDown: PointerEventHandler<HTMLButtonElement>;
  onPointerUp: PointerEventHandler<HTMLButtonElement>;
  onPointerCancel?: PointerEventHandler<HTMLButtonElement>;
  onKeyDown: KeyboardEventHandler<HTMLButtonElement>;
  onKeyUp: KeyboardEventHandler<HTMLButtonElement>;
  onBlur?: () => void;
  label?: string;
  statusLabel?: string;
}) {
  return (
    <div className="nb-talk-dock">
      <div className="nb-talk-hint">
        <span>Press & hold</span>
        <span className="nb-talk-key">SPACE</span>
        <span>or click</span>
      </div>
      <button
        type="button"
        aria-label={active ? "Release to finish" : label}
        disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel ?? onPointerUp}
        onKeyDown={onKeyDown}
        onKeyUp={onKeyUp}
        onBlur={onBlur}
        className={`nb-talk-btn ${active ? "nb-talk-btn-listening" : ""}`}
      >
        <span className="nb-talk-label">
          <Mic />
          {label}
        </span>
        <span className="nb-talk-waves" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <span key={i} />
          ))}
        </span>
      </button>
    </div>
  );
}

export function LiveTranscriptPanel({
  active,
  transcriptText,
}: {
  active: boolean;
  transcriptText: string;
}) {
  return (
    <div className="nb-card nb-transcript-card">
      <div className="nb-transcript-head">
        <h3>Live Transcript</h3>
        <div className="flex items-center gap-2.5">
          <div className={`nb-wave ${active ? "" : "nb-wave-standby"}`} aria-hidden="true">
            <span /><span /><span /><span /><span />
          </div>
          <span className="nb-chip">
            <span className={`nb-pulse ${active ? "" : "nb-pulse-muted"}`} />
            {active ? "Listening" : "Standby"}
          </span>
        </div>
      </div>
      <div className={`nb-transcript-body ${transcriptText ? "" : "nb-transcript-empty"}`}>
        {transcriptText || "Latest transcript will appear here."}
      </div>
    </div>
  );
}

export function DraftBrainPanel({
  draftText,
  dispatchPlan,
  summary,
  canSend,
  clearDisabled,
  sendDisabled,
  sending,
  clearing,
  error,
  onSend,
  onClear,
}: {
  draftText: string;
  dispatchPlan?: {
    target_agent: string;
    mode: string;
    task_title: string;
    missing_context?: string[];
  } | null;
  summary?: string;
  canSend: boolean;
  clearDisabled: boolean;
  sendDisabled: boolean;
  sending: boolean;
  clearing: boolean;
  error?: string | null;
  onSend: () => void;
  onClear: () => void;
}) {
  const charCount = draftText.length;

  return (
    <div className="nb-card nb-draft-card">
      <div className="nb-card-head">
        <div className="nb-card-label">Current Draft<span className="sr-only">Current draft</span></div>
        <div className="nb-card-hint">{draftText ? "auto-saved · just now" : "waiting"}</div>
      </div>
      {summary ? <p className="mt-2 text-[12px] leading-5 text-[#6b7280]">{summary}</p> : null}
      <div className="nb-draft-area">
        {draftText ? draftText : (
          <span className="nb-draft-placeholder">
            <span>No draft yet. Hold the mic to start shaping one.</span>
            <br />
            Tell your bro what to build.
          </span>
        )}
      </div>
      {dispatchPlan ? (
        <div className="mt-4 rounded-xl border border-[#e5e7eb] bg-white/70 px-4 py-3">
          <div className="nb-card-label text-[#9ca3af]">Dispatch plan</div>
          <div className="mt-3 grid gap-2 text-[12px] leading-5 text-[#4b5563]">
            <div><span className="font-semibold text-[#111827]">To:</span> {dispatchPlan.target_agent}</div>
            <div><span className="font-semibold text-[#111827]">Mode:</span> {dispatchPlan.mode}</div>
            <div><span className="font-semibold text-[#111827]">Task:</span> {dispatchPlan.task_title}</div>
            {(dispatchPlan.missing_context?.length ?? 0) > 0 ? (
              <div><span className="font-semibold text-[#111827]">Missing:</span> {dispatchPlan.missing_context?.join(", ")}</div>
            ) : null}
          </div>
        </div>
      ) : null}
      {error ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-600" role="status">
          {error}
        </div>
      ) : null}
      <div className="nb-draft-footer">
        <div className="nb-meta">
          <span><PencilLine />{charCount} chars</span>
        </div>
        <div className="nb-btn-row">
        <button
          type="button"
          className="nb-btn"
          disabled={clearDisabled}
          onClick={onClear}
        >
          <Trash2 />
          <span>{clearing ? "Clearing" : "Clear Draft"}</span>
        </button>
        <button
          type="button"
          className="nb-btn nb-btn-primary"
          disabled={sendDisabled || !canSend}
          onClick={onSend}
        >
          <span>{sending ? "Sending" : "Send to Bro"}</span>
          <SendHorizontal />
        </button>
        </div>
      </div>
    </div>
  );
}

function TaskHistoryCard({ record }: { record: BroTaskRecord }) {
  const isCompleted = record.status === "completed";
  const isRunning = record.status === "running";
  const tone = isCompleted ? "done" : isRunning ? "run" : "queued";

  return (
    <article className="nb-task-card" tabIndex={0}>
      <div className={`nb-task-icon nb-task-icon-${tone}`} aria-hidden="true">
        {isRunning ? <Play /> : <CheckCircle2 />}
      </div>
      <div className="nb-task-body">
        <div className="nb-task-top">
          <span className="nb-task-title">{record.title}</span>
          <span className={`nb-task-badge nb-task-badge-${tone}`}>{record.statusLabel}</span>
        </div>
        <p className="nb-task-desc">{record.description}</p>
        {record.timeLabel ? (
          <span className="nb-task-time">
            <Clock />
            {record.timeLabel}
          </span>
        ) : null}
      </div>
    </article>
  );
}

export function RunnerBrainPanel({
  bro,
  summary,
  taskRecords = [],
  agentEvents = [],
  activeTaskId,
  stoppingTask,
  stopTaskError,
  onStopTask,
}: {
  bro: BroCardModel;
  summary: TaskSummary | null;
  taskRecords?: BroTaskRecord[];
  agentEvents?: AgentEvent[];
  activeTaskId: string | null;
  stoppingTask: boolean;
  stopTaskError?: string | null;
  onStopTask: () => void;
}) {
  const isBusy = bro.status === "busy";
  const canStopTask = Boolean(activeTaskId) && isBusy;
  const primaryProgressDetail = bro.progressDetails[0];
  const taskProgress = Math.max(0, Math.min(100, Math.round(bro.progress)));
  const statusCardStyle = {
    "--nb-task-progress": `${taskProgress}%`,
  } as CSSProperties;

  return (
    <aside className="nb-rightpanel">
      <h2 className="sr-only">Runner workspace</h2>
      <div className="nb-status-card" style={statusCardStyle}>
        <div className="nb-status-head">
          <div className={`nb-bot-orb ${isBusy ? "nb-bot-orb-active" : ""}`} data-testid="bro-detail-bot-status-icon">
            <Bot className="h-5 w-5" />
            {isBusy ? <span className="nb-live-dot" /> : null}
          </div>
          <div className="nb-status-main">
            <div className="nb-status-row">
              <span className="nb-status-label">Current task:</span>
              <span className="nb-status-value">{isBusy ? "Running" : "Idle"}</span>
            </div>
            <div className="nb-status-desc">{bro.taskTitle || "Waiting for assignment"}</div>
          </div>
          <button
            type="button"
            aria-label="Stop Task"
            className="nb-status-stop"
            disabled={!canStopTask || stoppingTask}
            onClick={onStopTask}
          >
            {stoppingTask ? "Stopping" : "Stop Task"}
          </button>
        </div>
        <div className="nb-status-foot">
          <span className="nb-mini-dot" />
          {primaryProgressDetail ? (
            <MarkdownText className="nb-status-foot-detail">
              {primaryProgressDetail}
            </MarkdownText>
          ) : (
            <span>Ready to pick up the next runtime assignment.</span>
          )}
        </div>
      </div>
      {stopTaskError ? (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-600" role="status">
          {stopTaskError}
        </div>
      ) : null}

      {summary ? (
        <div className="nb-card px-4 py-3">
          <div className="nb-card-label text-[#9ca3af]">Latest summary</div>
          <MarkdownText className="mt-2 line-clamp-4 text-[13px] leading-6 text-[#6b7280] lg:line-clamp-none">
            {summary.conversational_summary ?? summary.operational_summary ?? ""}
          </MarkdownText>
        </div>
      ) : null}

      <div className="nb-card px-4 py-3">
        <div className="nb-card-label text-[#9ca3af]">Agent status timeline</div>
        <div className="mt-3 space-y-2">
          {agentEvents.length > 0 ? agentEvents.slice(-5).reverse().map((event) => (
            <div key={event.event_id} className="rounded-lg border border-[#e5e7eb] bg-white/70 px-3 py-2">
              <div className="flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.12em] text-[#9ca3af]">
                <span>{event.type}</span>
                <span>{event.delivery}</span>
              </div>
              <MarkdownText className="mt-1 text-[13px] leading-5 text-[#4b5563]">
                {event.message}
              </MarkdownText>
            </div>
          )) : (
            <div className="text-[13px] leading-6 text-[#9ca3af]">Progress events will appear here.</div>
          )}
        </div>
      </div>

      <div className="nb-card px-4 py-3">
        <div className="nb-card-label text-[#9ca3af]">Artifacts</div>
        <div className="mt-3 space-y-2">
          {agentEvents.filter((event) => event.artifact_id).length > 0 ? (
            agentEvents.filter((event) => event.artifact_id).slice(-5).reverse().map((event) => (
              <div key={event.event_id} className="flex items-center gap-2 rounded-lg border border-[#e5e7eb] bg-white/70 px-3 py-2 text-[13px] text-[#4b5563]">
                <FileText className="h-4 w-4 text-[#9ca3af]" />
                <span>{event.artifact_id}</span>
              </div>
            ))
          ) : (
            <div className="text-[13px] leading-6 text-[#9ca3af]">No artifacts yet.</div>
          )}
        </div>
      </div>

      <div className="nb-tasks-head">
        <div>
          <h3>Recent tasks</h3>
          <div className="nb-tasks-sub">Recent to earliest</div>
        </div>
        <span className="nb-count-pill">{taskRecords.length}</span>
      </div>

      <div className="nb-task-list">
        {taskRecords.length > 0 ? (
          taskRecords.map((record) => <TaskHistoryCard key={record.taskId} record={record} />)
        ) : (
          <article className="nb-empty-state">
            No recent tasks yet.
          </article>
        )}
      </div>

    </aside>
  );
}

export function BroDetailHeader({
  bro,
  onBack,
}: {
  bro: BroCardModel;
  onBack: () => void;
}) {
  return (
    <>
      <div className="nb-detail-topbar">
        <div className="nb-detail-crumb">
          <span className="sr-only">Bro detail</span>
          <span>Workspace</span>
          <span className="nb-detail-crumb-sep">/</span>
          <span>Bros</span>
          <span className="nb-detail-crumb-sep">/</span>
          <span className="nb-detail-crumb-current">Bro Detail</span>
        </div>
        <div className="nb-detail-actions">
          <button type="button" className="nb-back-btn" onClick={onBack}>
            <ArrowLeft />
            Back home
          </button>
        </div>
      </div>
      <div className="nb-detail-bro-header">
        <div className="nb-detail-bro-identity">
          <BroPortrait bro={bro} active={bro.status === "busy"} talking={false} />
          <div className="nb-detail-bro-title">
            <h1>{bro.name}</h1>
            <span className="nb-chip nb-chip-online">
              <span className="nb-pulse" />
              {bro.status === "busy" ? "Runtime running" : "Runtime standby"}
            </span>
            <span className="nb-chip nb-chip-muted">
              <span className="nb-pulse nb-pulse-muted" />
              {bro.liveState}
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

export function StatusPill({ children }: { children: ReactNode }) {
  return (
    <span className="command-chip px-3 py-1 text-[11px]">
      {children}
    </span>
  );
}
