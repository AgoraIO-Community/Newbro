export type ConnectionStatus =
  | "booting"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export type SessionActionType =
  | "send_message"
  | "send_command"
  | "resolve_interaction_request"
  | "submit_asr_turn"
  | "send_draft"
  | "clear_draft";

export type TaskStatus =
  | "created"
  | "queued"
  | "waiting_executor"
  | "running"
  | "waiting_user_input"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "stopped";

export type RunStatus =
  | "created"
  | "assigned"
  | "waiting_executor"
  | "running"
  | "blocked"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type TaskCommandType =
  | "pause_task"
  | "cancel_task"
  | "preempt_task"
  | "resume_task"
  | "retry_task";

export type InteractionRequestKind = "permission" | "question" | "confirmation" | "plan_proposal";
export type InteractionRequestStatus =
  | "pending"
  | "approved"
  | "denied"
  | "answered"
  | "resolved"
  | "cancelled"
  | "expired";

export type AttentionItemKind =
  | "permission_request"
  | "question_request"
  | "confirmation_request"
  | "plan_proposal_request"
  | "task_paused"
  | "task_resumed"
  | "task_blocked"
  | "task_completed";

export type AttentionItemStatus = "active" | "acted" | "dismissed" | "expired";

export interface Task {
  task_id: string;
  root_task_id: string;
  parent_task_id: string | null;
  title: string;
  goal: string;
  status: TaskStatus;
  priority: number;
  interruptible: boolean;
  requires_confirmation: boolean;
  preferred_executor: string | null;
  session_affinity: string | null;
  task_revision: number;
  latest_instruction: string | null;
  metadata: Record<string, unknown>;
}

export interface TaskMutation {
  mutation_id: string;
  task_id: string | null;
  mutation_type: string;
  patch: Record<string, unknown>;
  created_by: string;
  urgency: string;
  effective_scope: string;
  requires_replan: boolean;
}

export interface TaskCommand {
  command_id: string;
  task_id: string;
  command_type: TaskCommandType;
  payload: Record<string, unknown>;
  created_by: string;
  reason: string | null;
}

export interface AgentResumeHandle {
  executor_id: string;
  session_handle: string | null;
  turn_handle: string | null;
  opaque: Record<string, unknown>;
}

export interface QueuedRunRequest {
  queued_request_id: string;
  task_id: string;
  executor_config: Record<string, unknown>;
  latest_instruction: string;
  requested_by_message_id: string | null;
}

export interface ExecutionSession {
  execution_session_id: string;
  task_id: string;
  base_executor_id: string;
  executor_node_id: string | null;
  continuity_key: string | null;
  run_ids: string[];
  active_run_id: string | null;
  latest_run_id: string | null;
  latest_resume_handle: AgentResumeHandle | null;
  queued_run_request: QueuedRunRequest | null;
}

export interface BroThread {
  thread_id: string;
  persona_id: string;
  persona_name: string | null;
  executor_id: string;
  executor_node_id: string | null;
  workspace_id?: string | null;
  workspace_name?: string | null;
  execution_session_id: string | null;
  status: "pending" | "queued" | "running" | "blocked" | "completed" | "failed" | "cancelled";
  title: string;
  preview: string | null;
  progress: number;
  task_ids: string[];
  active_task_id: string | null;
  latest_task_id: string | null;
  has_resume_handle: boolean;
  updated_at: string | null;
  timeline_status: "not_loaded" | "loading" | "loaded" | "failed";
  timeline_error: string | null;
  diagnostics: Record<string, unknown>;
}

export interface BroTimelineMessage {
  message_id: string;
  role: "user" | "assistant";
  kind: "text" | "audio";
  text: string | null;
  transcript: string | null;
  audio_id: string | null;
  duration_ms: number | null;
  created_at: string | null;
  updated_at: string | null;
  status: string;
  metadata: Record<string, unknown>;
}

export interface BroTimelinePlanStep {
  step: string;
  status: "pending" | "inProgress" | "completed";
}

export interface BroTimelinePlan {
  text: string | null;
  explanation: string | null;
  steps: BroTimelinePlanStep[];
}

export interface BroTimelineTask {
  task_id: string;
  run_id: string | null;
  title: string;
  status: string;
  status_label: string;
  progress: number;
  goal: string | null;
  plan: BroTimelinePlan | null;
  description: string | null;
  summary: string | null;
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface BroTimelineTurn {
  turn_id: string;
  thread_id: string;
  persona_id: string;
  executor_id: string;
  owner: "newbro" | "executor";
  client_request_id: string | null;
  executor_thread_id: string | null;
  executor_turn_id: string | null;
  input_modality: "text" | "audio" | "unknown";
  user: BroTimelineMessage | null;
  assistant: BroTimelineMessage | null;
  task: BroTimelineTask | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface CursorPageInfo {
  next_cursor: string | null;
  previous_cursor: string | null;
  has_more: boolean;
  status: "not_loaded" | "loading" | "loaded" | "failed";
  error: string | null;
}

export interface BroThreadPageResponse {
  persona_id: string;
  threads: BroThread[];
  page: CursorPageInfo;
}

export interface BroTimelineTurnPageResponse {
  thread_id: string;
  thread: BroThread;
  turns: BroTimelineTurn[];
  page: CursorPageInfo;
}

export interface ExecutorSkill {
  name: string;
  display_name: string;
  description: string;
  hint: string | null;
  path: string;
  enabled: boolean;
}

export interface BroExecutorCapabilitySummary {
  version: string | null;
  minimum_version: string | null;
  availability_reason: string | null;
  supports_thread_list: boolean;
  supports_audio_instruction: boolean;
  skills: ExecutorSkill[];
}

export interface BroExecutorNodeSummary {
  node_id: string;
  name: string;
  connection_status: "connected" | "disconnected";
  enabled_executors: string[];
  last_connected_at: string | null;
  codex: BroExecutorCapabilitySummary | null;
}

export interface BroSummary {
  persona_id: string;
  name: string;
  avatar: string;
  status: "idle" | "busy";
  executor_node: BroExecutorNodeSummary | null;
}

export interface BroListResponse {
  bros: BroSummary[];
}

export interface BroThreadSubscriptionResponse {
  thread_id: string;
  persona_id: string;
  subscribed: boolean;
  timeline_status: "not_loaded" | "loading" | "loaded" | "failed";
  timeline_error: string | null;
}

export interface OutboundTurnRequest {
  request_id: string;
  persona_id: string;
  executor_id: string;
  executor_node_id: string;
  target_thread_id: string | null;
  create_new_thread: boolean;
  workspace_id: string | null;
  client_request_id: string | null;
  input_modality: "text" | "audio";
  text: string | null;
  audio_instruction_id: string | null;
  plan_mode: boolean;
  status: "pending" | "accepted" | "running" | "completed" | "failed";
  error: string | null;
  executor_thread_id: string | null;
  executor_turn_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface ExecutionRun {
  run_id: string;
  task_id: string;
  execution_session_id: string;
  executor_type: string;
  status: RunStatus;
  claimed_by: string | null;
  run_revision: number;
  latest_progress_message: string | null;
  output_summary: string | null;
  block_reason: string | null;
  failure_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface ExecutionDetailEntry {
  detail_id: string;
  task_id: string;
  run_id: string;
  execution_session_id: string;
  event_type: string;          // PROGRESS | PLAN | WAITING_EXECUTOR | BLOCKED | COMPLETED | FAILED | CANCELLED
  text: string;
  created_at: string;
  payload?: Record<string, unknown>;
}

export interface NativeReasoningStep {
  item_id: string;
  text: string;
  kind: "progress" | "plan";
  created_at: string;
}

export type ExecutionMode = "undecided" | "lightweight" | "managed";

export interface TaskExecutionMode {
  task_id: string;
  mode: ExecutionMode;
  decided_from_run_id: string | null;
  elapsed_seconds: number;
}

export interface SessionBinding {
  task_id: string;
  execution_session_id: string | null;
  executor_node_id: string | null;
  session_id: string | null;
  claimed_by: string | null;
  claim_expires_at: string | null;
  execution_revision: number;
  binding_status: string;
}

export interface TaskSummary {
  task_id: string;
  operational_summary: string | null;
  conversational_summary: string | null;
  latest_user_visible_status: string | null;
  needs_user_input: boolean;
}

export type NotificationCandidateType = "completed" | "blocked" | "needs_input";
export type NotificationDeliveryStatus = "pending" | "emitted" | "suppressed";

export interface NotificationCandidate {
  candidate_id: string;
  task_id: string;
  candidate_type: NotificationCandidateType;
  priority: string;
  summary_short: string;
  source_run_id: string | null;
  created_at: string;
  delivery_status: NotificationDeliveryStatus;
  merge_key: string;
  requires_immediate_delivery: boolean;
}

export interface InteractionRequest {
  request_id: string;
  task_id: string;
  execution_session_id: string | null;
  run_id: string | null;
  executor_type: string | null;
  kind: InteractionRequestKind;
  status: InteractionRequestStatus;
  prompt: string;
  details: Record<string, unknown>;
  available_actions: string[];
  answer_schema: Record<string, unknown> | null;
  resume_strategy: string;
  opaque: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
}

export interface AttentionItem {
  attention_id: string;
  source: string;
  kind: AttentionItemKind;
  priority: string;
  status: AttentionItemStatus;
  title: string;
  body: string;
  task_id: string | null;
  request_id: string | null;
  actions: Array<Record<string, unknown>>;
  dedupe_key: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Draft {
  text: string;
  last_update_summary: string;
  task_spec?: Record<string, unknown> | null;
  missing_context?: string[];
  revision_id?: string | null;
  revision_number?: number;
  updated_at?: string | null;
}

export interface DraftSession {
  id: string;
  assigned_bro_id: string;
  status: "empty" | "drafting" | "ready" | "sent" | "cleared";
  current_draft: Draft | null;
  current_dispatch_plan?: DispatchPlan | null;
  runtime_state?: string;
  current_revision_id?: string | null;
  current_revision_number?: number;
  live_classification?: Record<string, unknown> | null;
  live_source_boundary?: string | null;
  live_transcript_timestamp_ms?: number | null;
  asr_turns: Array<Record<string, unknown>>;
  snapshots: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface DispatchPlan {
  plan_id: string;
  session_id: string;
  draft_session_id: string;
  draft_revision_id?: string | null;
  draft_revision_number?: number;
  intent: string;
  target_agent: string;
  task_title: string;
  task_goal: string;
  required_context: string[];
  missing_context: string[];
  mode: string;
  risk_level: string;
  confidence: number;
  requires_user_confirmation: boolean;
  user_confirmed: boolean;
  output_language: string;
  task_spec: Record<string, unknown>;
}

export interface AgentEvent {
  event_id: string;
  task_id: string;
  agent_id: string;
  type: string;
  message: string;
  importance: "low" | "medium" | "high" | "urgent";
  delivery: "silent" | "silent_ui" | "badge" | "short_voice" | "voice_interrupt";
  artifact_id: string | null;
  created_at: string;
}

export interface ExecutorCapability {
  executor_type: string;
  supports_pause: boolean;
  supports_cancel: boolean;
  supports_resume: boolean;
  connected?: boolean;
  node_id?: string | null;
  availability_reason?: string | null;
  supports_follow_up: boolean;
  supports_audio_instruction?: boolean;
  supports_thread_list?: boolean;
}

export interface ExecutorNodeRecord {
  node_id: string;
  name: string;
  enabled_executors: string[];
  acpx_agent?: string | null;
  connected_executors: string[];
  connected_executor_capabilities?: ExecutorCapability[];
  connection_status: "connected" | "disconnected";
  token_hint: string | null;
  last_connected_at: string | null;
  last_seen_at: string | null;
}

export interface ExecutorNodeCredentialIssue {
  node: ExecutorNodeRecord;
  token: string;
}

export interface ConversationHistoryEntry {
  role: string;
  text: string;
  message_id: string;
  created_at: string;
}

export interface SessionSnapshot {
  session_id: string;
  voice_target_persona_id?: string | null;
  tasks: Task[];
  execution_sessions: ExecutionSession[];
  execution_runs: ExecutionRun[];
  recent_execution_details: Record<string, ExecutionDetailEntry[]>;
  recent_native_turn_reasoning: Record<string, NativeReasoningStep[]>;
  execution_modes: TaskExecutionMode[];
  bindings: SessionBinding[];
  summaries: TaskSummary[];
  notification_candidates: NotificationCandidate[];
  outbound_turn_requests: OutboundTurnRequest[];
  bro_threads: BroThread[];
  bro_timeline_turns: BroTimelineTurn[];
  bro_thread_pages?: Record<string, CursorPageInfo>;
  bro_timeline_pages?: Record<string, CursorPageInfo>;
  personas: Persona[];
  interaction_requests: InteractionRequest[];
  attention_items: AttentionItem[];
  agent_events: AgentEvent[];
  executor_capabilities: ExecutorCapability[];
  executor_nodes: ExecutorNodeRecord[];
  draft_session: DraftSession | null;
}

export interface Persona {
  persona_id: string;
  name: string;
  avatar: string;
  base_prompt: string;
  executor_node_id: string | null;
  bro_detail_session_id: string;
  status: "idle" | "busy";
}

export interface ConversationSnapshot {
  session_id: string;
  conversation_history: ConversationHistoryEntry[];
}

export interface SessionResponse {
  session_id: string;
}

export type DiagnosticLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export interface DiagnosticEvent {
  sequence: number;
  ts: string;
  level: DiagnosticLevel;
  event_name: string;
  service: string;
  component: string;
  conversation_id: string | null;
  request_id: string | null;
  task_id: string | null;
  run_id: string | null;
  execution_session_id: string | null;
  executor_session_id: string | null;
  notification_id: string | null;
  trace_id: string | null;
  worker_id: string | null;
  executor_type: string | null;
  outcome: string | null;
  reason_code: string | null;
  summary: string;
  details: Record<string, unknown>;
  app_version: string | null;
  git_sha: string | null;
  model_name: string | null;
  settings_fingerprint: string | null;
}

export interface DiagnosticTimelineResponse {
  events: DiagnosticEvent[];
}

export interface SnapshotDiffItem {
  id: string;
  entityKind: string;
  entityId: string;
  changeType: string;
  taskId?: string | null;
  details: string;
}

export interface StreamEventBase {
  sequence: number;
  type: string;
}

export interface SnapshotStreamEvent extends StreamEventBase {
  type: "snapshot";
  snapshot: SessionSnapshot;
}

export interface BroListInvalidatedStreamEvent extends StreamEventBase {
  type: "bro_list_invalidated";
  reason: "executor_node_connected" | "executor_node_disconnected" | "executor_node_changed" | "persona_changed";
  node_id: string | null;
}

export interface ActionAcceptedStreamEvent extends StreamEventBase {
  type: "action_accepted";
  request_id: string;
  action_type: SessionActionType;
}

export interface ActionRejectedStreamEvent extends StreamEventBase {
  type: "action_rejected";
  request_id: string;
  action_type: SessionActionType | "unknown";
  error_code: string;
  message: string;
}

export interface UserMessageAppendedStreamEvent extends StreamEventBase {
  type: "user_message_appended";
  message_id: string;
  role: "user";
  text: string;
  source: "user" | "connector";
  created_at: string;
}

export interface AssistantResponseStartedStreamEvent extends StreamEventBase {
  type: "assistant_response_started";
  request_id: string;
}

export interface AssistantResponseDeltaStreamEvent extends StreamEventBase {
  type: "assistant_response_delta";
  request_id: string;
  delta: string;
}

export interface AssistantResponseCompletedStreamEvent extends StreamEventBase {
  type: "assistant_response_completed";
  request_id: string;
  message_id: string;
  reply_text: string;
  conversational_act: string;
  affected_task_ids: string[];
  created_at: string;
}

export interface AssistantResponseFailedStreamEvent extends StreamEventBase {
  type: "assistant_response_failed";
  request_id: string;
  message: string;
}

export interface DraftOutputStartedStreamEvent extends StreamEventBase {
  type: "draft_output_started";
  request_id: string;
}

export interface DraftOutputDeltaStreamEvent extends StreamEventBase {
  type: "draft_output_delta";
  request_id: string;
  delta: string;
}

export interface DraftOutputCompletedStreamEvent extends StreamEventBase {
  type: "draft_output_completed";
  request_id: string;
  draft_session_id: string;
  draft_text: string;
}

export interface DraftOutputFailedStreamEvent extends StreamEventBase {
  type: "draft_output_failed";
  request_id: string;
  message: string;
}

export interface ConversationAppendedStreamEvent extends StreamEventBase {
  type: "conversation_appended";
  message_id: string;
  role: "assistant";
  text: string;
  source: "notification" | "system_fallback";
  created_at: string;
}

export type SessionStreamEvent =
  | SnapshotStreamEvent
  | BroListInvalidatedStreamEvent
  | ActionAcceptedStreamEvent
  | ActionRejectedStreamEvent
  | UserMessageAppendedStreamEvent
  | AssistantResponseStartedStreamEvent
  | AssistantResponseDeltaStreamEvent
  | AssistantResponseCompletedStreamEvent
  | AssistantResponseFailedStreamEvent
  | DraftOutputStartedStreamEvent
  | DraftOutputDeltaStreamEvent
  | DraftOutputCompletedStreamEvent
  | DraftOutputFailedStreamEvent
  | ConversationAppendedStreamEvent;
