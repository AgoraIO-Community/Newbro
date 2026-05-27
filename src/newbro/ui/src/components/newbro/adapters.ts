import type { BroThread, ExecutionRun, Task, TaskStatus, TaskSummary } from "../../types";
import type { BroCardModel, BroTaskRecord, BroThreadRecord, RuntimeExecutorNodeInput, RuntimePersonaInput } from "./types";

const avatarCycle = ["fox", "cat", "bunny", "bro"] as const;

function hashValue(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function selectAvatarType(persona: RuntimePersonaInput): BroCardModel["avatarType"] {
  const seed = `${persona.persona_id}:${persona.name}:${persona.avatar ?? ""}`;
  return avatarCycle[hashValue(seed) % avatarCycle.length];
}

function buildLiveState(
  persona: RuntimePersonaInput,
  nodesById: Map<string, RuntimeExecutorNodeInput>,
): BroCardModel["liveState"] {
  if (!persona.executor_node_id) {
    return "unbound";
  }
  const node = nodesById.get(persona.executor_node_id);
  if (node?.connection_status === "connected") {
    return "live";
  }
  return "offline";
}

function buildBusyDetails(
  persona: RuntimePersonaInput,
  liveState: BroCardModel["liveState"],
  nodeName: string | null,
) {
  const taskHandle = persona.current_task_id ? persona.current_task_id.slice(0, 8) : "current queue";
  const nodeLabel = nodeName ?? "an unbound route";
  return [
    `Tracking live runtime work for ${taskHandle}.`,
    "Preparing the next handoff and status update.",
    liveState === "live"
      ? `Bound to ${nodeLabel} and ready for local execution.`
      : liveState === "offline"
        ? `${nodeLabel} is offline, so this bro is standing by for reconnection.`
        : "Needs an executor node binding before this bro can go live.",
  ];
}

function buildIdleDetails(liveState: BroCardModel["liveState"], nodeName: string | null) {
  const nodeLabel = nodeName ?? "an executor node";
  if (liveState === "live") return [];
  return [
    liveState === "offline"
      ? `Bound to ${nodeLabel}, but waiting for it to reconnect.`
      : "Bind this bro to an executor node to make it live.",
  ];
}

function buildIdleNote(liveState: BroCardModel["liveState"], nodeName: string | null): string {
  const nodeLabel = nodeName ?? "a node";
  if (liveState === "live") {
    return `${nodeLabel} is connected. This bro can pick up the next task immediately.`;
  }
  if (liveState === "offline") {
    return `${nodeLabel} is assigned but offline. This bro will stay dark until it reconnects.`;
  }
  return "No executor node is bound yet. Bind one from Bros or Nodes to bring this bro online.";
}

function taskStatusLabel(status: TaskStatus): string {
  if (status === "waiting_executor") return "Waiting for executor";
  if (status === "waiting_user_input") return "Waiting for input";
  return status.replace(/_/g, " ");
}

function threadStatusLabel(status: BroThread["status"]): string {
  if (status === "blocked") return "Waiting for input";
  return status.replace(/_/g, " ");
}

function taskStatusProgress(status: TaskStatus): number {
  if (status === "completed") return 100;
  if (status === "running") return 60;
  if (status === "waiting_user_input" || status === "waiting_executor") return 35;
  if (status === "queued" || status === "created") return 18;
  if (status === "paused") return 45;
  return 30;
}

function uniqueDetails(details: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const detail of details) {
    const normalized = detail?.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function latestRunsByTaskId(executionRuns?: ExecutionRun[] | null): Map<string, ExecutionRun> {
  const runsByTaskId = new Map<string, ExecutionRun>();
  for (const run of executionRuns ?? []) {
    const existing = runsByTaskId.get(run.task_id);
    if (!existing || run.run_revision > existing.run_revision) {
      runsByTaskId.set(run.task_id, run);
    }
  }
  return runsByTaskId;
}

function taskBelongsToBro(task: Task, broId: string, activeTaskId?: string | null): boolean {
  return (
    task.task_id === activeTaskId
    || task.metadata.persona_id === broId
    || task.metadata.assigned_bro_id === broId
  );
}

function taskRecordSummary(
  task: Task,
  run: ExecutionRun | undefined,
  summary: TaskSummary | undefined,
): string {
  return (
    summary?.conversational_summary
    ?? summary?.operational_summary
    ?? run?.output_summary
    ?? run?.failure_reason
    ?? run?.block_reason
    ?? run?.latest_progress_message
    ?? task.goal
  );
}

function taskRecordDescription(summary: string): string {
  return summary
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/<[^>]+>/g, " ")
    .replace(/[*_~#>]+/g, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function metadataString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function formatRelativeTime(value: string): string | undefined {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return undefined;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function taskRecordTimeLabel(task: Task): string | undefined {
  const value =
    metadataString(task.metadata, "updated_at")
    ?? metadataString(task.metadata, "completed_at")
    ?? metadataString(task.metadata, "created_at");
  return value ? formatRelativeTime(value) : undefined;
}

function threadTimeLabel(thread: BroThread): string | undefined {
  return thread.updated_at ? formatRelativeTime(thread.updated_at) : undefined;
}

export function buildBroThreadRecords(
  broId: string,
  threads?: BroThread[] | null,
): BroThreadRecord[] {
  return (threads ?? [])
    .filter((thread) => thread.persona_id === broId)
    .map((thread) => ({
      threadId: thread.thread_id,
      title: thread.title || "Current session",
      status: thread.status,
      statusLabel: threadStatusLabel(thread.status),
      preview: thread.preview?.trim() || "No output yet.",
      progress: thread.progress,
      taskIds: thread.task_ids,
      activeTaskId: thread.active_task_id,
      latestTaskId: thread.latest_task_id,
      hasResumeHandle: thread.has_resume_handle,
      timeLabel: threadTimeLabel(thread),
    }));
}

function buildTaskRecord(
  task: Task,
  run: ExecutionRun | undefined,
  summary: TaskSummary | undefined,
): BroTaskRecord {
  const recordSummary = taskRecordSummary(task, run, summary);
  const status = run?.status === "completed" ? "completed" : task.status;
  const sourceKind = metadataString(task.metadata, "source_kind");
  const userText = sourceKind === "codex_thread_history"
    ? task.latest_instruction?.trim() ?? ""
    : sourceKind === "bro_detail_text" || sourceKind === "bro_detail_ptt"
      ? (task.latest_instruction?.trim() || task.goal.trim() || task.title.trim())
      : "";
  return {
    taskId: task.task_id,
    title: task.title,
    userText: userText || undefined,
    status,
    statusLabel: taskStatusLabel(status),
    progress: taskStatusProgress(status),
    description: taskRecordDescription(recordSummary),
    summary: recordSummary,
    timeLabel: taskRecordTimeLabel(task),
  };
}

function normalizeProgressCandidate(value: string | null | undefined): string | null {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : null;
}

function isPlaceholderProgressText(value: string, task: Task | null): boolean {
  if (!task) return false;
  const normalized = value.toLowerCase();
  const title = task.title.trim().toLowerCase();
  const goal = task.goal.trim().toLowerCase();
  const instruction = task.latest_instruction?.trim().toLowerCase() ?? "";
  const placeholderTexts = [
    title,
    goal,
    instruction,
    `running: ${title}`,
    `queued: ${title}`,
    `completed: ${title}`,
    `paused: ${title}`,
    `cancelled: ${title}`,
    `failed: ${title}`,
    `waiting for executor node: ${title}`,
    `i queued ${title} again.`,
    `i paused ${title}.`,
  ].filter(Boolean);
  return placeholderTexts.includes(normalized);
}

function progressDetailsFromRuntime(
  task: Task | null,
  run: ExecutionRun | null,
  summary: TaskSummary | null,
): string[] {
  const directDetails = uniqueDetails([
    run?.latest_progress_message,
    run?.output_summary,
    run?.block_reason ? `Blocked: ${run.block_reason}` : null,
    run?.failure_reason ? `Failed: ${run.failure_reason}` : null,
  ]);
  if (directDetails.length > 0) return directDetails;

  return uniqueDetails([
    normalizeProgressCandidate(summary?.conversational_summary),
    normalizeProgressCandidate(summary?.operational_summary),
  ].filter((value) => value && !isPlaceholderProgressText(value, task)));
}

export function buildBroTaskRecords(
  broId: string,
  options: {
    activeTaskId?: string | null;
    broDetailSessionId?: string | null;
    tasks?: Task[] | null;
    executionRuns?: ExecutionRun[] | null;
    summaries?: TaskSummary[] | null;
    taskIds?: string[] | null;
    limit?: number;
  },
): BroTaskRecord[] {
  const runsByTaskId = latestRunsByTaskId(options.executionRuns);
  const summaryByTaskId = new Map((options.summaries ?? []).map((summary) => [summary.task_id, summary]));
  const allowedTaskIds = options.taskIds ? new Set(options.taskIds) : null;
  const tasks = allowedTaskIds
    ? (options.tasks ?? []).filter((task) => allowedTaskIds.has(task.task_id))
    : options.tasks ?? [];
  const records: BroTaskRecord[] = [];
  const activeTask = options.activeTaskId
    ? tasks.find((task) => task.task_id === options.activeTaskId && taskBelongsToBro(task, broId, options.activeTaskId))
    : null;
  if (
    activeTask
    && (
      !options.broDetailSessionId
      || activeTask.metadata.bro_detail_session_id === options.broDetailSessionId
    )
  ) {
    records.push(
      buildTaskRecord(
        activeTask,
        runsByTaskId.get(activeTask.task_id),
        summaryByTaskId.get(activeTask.task_id),
      ),
    );
  }
  for (const task of [...tasks].reverse()) {
    if (task.task_id === activeTask?.task_id) continue;
    if (!taskBelongsToBro(task, broId, options.activeTaskId)) continue;
    if (
      options.broDetailSessionId
      && task.metadata.bro_detail_session_id !== options.broDetailSessionId
    ) {
      continue;
    }
    const run = runsByTaskId.get(task.task_id);
    const summary = summaryByTaskId.get(task.task_id);
    records.push(buildTaskRecord(task, run, summary));
    if (records.length >= (options.limit ?? 5)) break;
  }
  return records;
}

export function buildBroCardModels(
  personas?: RuntimePersonaInput[] | null,
  executorNodes?: RuntimeExecutorNodeInput[] | null,
  executionRuns?: ExecutionRun[] | null,
  summaries?: TaskSummary[] | null,
  tasks?: Task[] | null,
): BroCardModel[] {
  if (!personas) {
    return [];
  }
  if (personas.length === 0) {
    return [];
  }
  const taskByTaskId = new Map((tasks ?? []).map((task) => [task.task_id, task]));
  const nodesById = new Map((executorNodes ?? []).map((node) => [node.node_id, node]));
  const runsByTaskId = latestRunsByTaskId(executionRuns);
  const summaryByTaskId = new Map((summaries ?? []).map((s) => [s.task_id, s]));

  return personas.map((persona) => {
    const busy = persona.status === "busy" || persona.current_task_id !== null;
    const nodeName = persona.executor_node_id ? (nodesById.get(persona.executor_node_id)?.name ?? null) : null;
    const liveState = buildLiveState(persona, nodesById);

    // Pull real execution data when available
    const activeTask = persona.current_task_id ? (taskByTaskId.get(persona.current_task_id) ?? null) : null;
    const activeRun = persona.current_task_id ? runsByTaskId.get(persona.current_task_id) : null;
    const activeSummary = persona.current_task_id ? summaryByTaskId.get(persona.current_task_id) : null;

    const progressDetailsFromData = progressDetailsFromRuntime(activeTask, activeRun ?? null, activeSummary ?? null);
    const runStatus = activeRun?.status ?? null;
    const taskStatus = activeTask?.status ?? null;

    // Build progress details from real data
    let progressDetails: string[];
    let taskTitle: string;
    let progressLabel: string;
    let progress: number;

    if (busy && progressDetailsFromData.length > 0) {
      progressDetails = progressDetailsFromData;
      taskTitle = activeTask?.title ?? activeSummary?.latest_user_visible_status ?? "Handle active runtime work";
      progressLabel = runStatus === "running" ? "Running" : runStatus ?? (taskStatus ? taskStatusLabel(taskStatus) : "Syncing");
      progress = runStatus === "completed" ? 100 : runStatus === "running" ? 60 : taskStatus ? taskStatusProgress(taskStatus) : 30;
    } else if (busy && activeTask) {
      progressDetails = [];
      taskTitle = activeTask.title;
      progress = taskStatusProgress(activeTask.status);
      progressLabel = taskStatusLabel(activeTask.status);
    } else if (busy) {
      progressDetails = buildBusyDetails(persona, liveState, nodeName);
      taskTitle = "Handle active runtime work";
      progress = 42 + (hashValue(persona.persona_id) % 37);
      progressLabel = `${progress}% synced`;
    } else {
      progressDetails = buildIdleDetails(liveState, nodeName);
      taskTitle = "Waiting for assignment";
      progress = 0;
      progressLabel = "Idle";
    }

    return {
      id: persona.persona_id,
      name: persona.name.trim() || "Unnamed Bro",
      role: busy ? "Runtime operator" : "Runtime standby",
      status: busy ? "busy" : "idle",
      liveState,
      executorNodeId: persona.executor_node_id,
      nodeName,
      avatarType: selectAvatarType(persona),
      taskTitle,
      progress,
      progressLabel,
      progressDetails,
      idleNote: buildIdleNote(liveState, nodeName),
      source: "runtime",
    };
  });
}
