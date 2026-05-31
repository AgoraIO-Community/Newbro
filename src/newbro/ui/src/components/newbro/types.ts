import type { BroThread, BroTimelinePlan, ExecutorNodeRecord, Persona, TaskStatus } from "../../types";

export type NavItem = {
  label: string;
  active: boolean;
};

export type AvatarType = "avatar_1" | "avatar_2" | "avatar_3" | "avatar_4";

export type BroStatus = "busy" | "idle";
export type BroLiveState = "live" | "offline" | "unbound";

export type BroCardModel = {
  id: string;
  name: string;
  role: string;
  status: BroStatus;
  liveState: BroLiveState;
  executorNodeId: string | null;
  nodeName: string | null;
  executorType: string | null;
  avatarType: AvatarType;
  taskTitle: string;
  progress: number;
  progressLabel: string;
  progressDetails: string[];
  idleNote: string;
  latestReasoningStep: string | null;
  source: "sample" | "runtime";
};

export type BroTaskRecord = {
  taskId: string;
  title: string;
  userText?: string;
  goal?: string;
  plan?: BroTimelinePlan;
  status: TaskStatus;
  statusLabel: string;
  progress: number;
  description: string;
  summary: string;
  timestamp?: string;
  timeLabel?: string;
  timestampLabel?: string;
};

export type BroThreadRecord = {
  threadId: string;
  title: string;
  status: BroThread["status"];
  statusLabel: string;
  preview: string;
  progress: number;
  taskIds: string[];
  activeTaskId: string | null;
  latestTaskId: string | null;
  hasResumeHandle: boolean;
  workspaceId: string | null;
  workspaceName: string | null;
  timelineStatus: BroThread["timeline_status"];
  timelineError: string | null;
  timeLabel?: string;
};

export type RuntimePersonaInput = Pick<
  Persona,
  "persona_id" | "name" | "avatar" | "status" | "executor_node_id" | "bro_detail_session_id"
>;

export type RuntimeExecutorNodeInput = Pick<
  ExecutorNodeRecord,
  "node_id" | "name" | "connection_status" | "enabled_executors"
>;
