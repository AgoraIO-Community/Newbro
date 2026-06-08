import {
  buildReasoningStepsForNativeTurn,
  buildReasoningStepsForTurn,
  type ReasoningStep,
} from "../components/newbro/adapters";
import { deriveLiveTurnState, type LiveTurnState } from "./reasoningPhase";
import { splitLiveSteps } from "./splitLiveSteps";
import { timelineMessageText } from "./timelineMessage";
import type { BroTimelineTurn, ExecutionDetailEntry, ExecutionRun, NativeReasoningStep } from "../types";
import type { BroTaskRecord } from "../components/newbro/types";

export interface TurnRenderDeps {
  executionRuns: ExecutionRun[];
  recentExecutionDetails: Record<string, ExecutionDetailEntry[]>;
  recentNativeTurnReasoning: Record<string, NativeReasoningStep[]>;
}

export interface TurnRenderModel {
  liveState: LiveTurnState;
  activeCommentary: string | null;
  stepsForBubble: ReasoningStep[];
  dedupedSettledSteps: ReasoningStep[];
  answerText: string;
  settledHasNothing: boolean;
  canStop: boolean;
  stopTaskId: string | null;
}

/**
 * Decide how a single timeline turn renders. Pure: every input is passed in, so it
 * is unit-testable without React/shell context. This is the extracted decision that
 * was inline in TimelineTurnView; it owns the codex multi-message turn split on the
 * UI side (see AGENTS.md Golden Rule #3 and lib/splitLiveSteps).
 */
export function buildTurnRenderModel(
  turn: BroTimelineTurn,
  record: BroTaskRecord | null,
  deps: TurnRenderDeps,
): TurnRenderModel {
  const taskId = turn.task?.task_id ?? null;
  const activeRun = taskId
    ? (deps.executionRuns.find((r) => r.task_id === taskId && (r.status === "running" || r.status === "created" || r.status === "waiting_executor")) ?? null)
    : null;
  // For settled turns, find any run for this task (including completed runs).
  const anyRun = activeRun ?? (taskId ? (deps.executionRuns.find((r) => r.task_id === taskId) ?? null) : null);
  const details = taskId ? (deps.recentExecutionDetails[taskId] ?? null) : null;
  const nativeReasoningSteps = buildReasoningStepsForNativeTurn(turn, deps.recentNativeTurnReasoning);
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
  // Codex multi-message turn split: while reasoning the latest step is the prominent
  // streaming commentary line and the rest are compact steps; on answering/settled
  // commentary collapses into the (deduped) step list and the final answer is the
  // answer. See lib/splitLiveSteps for the contract.
  const { activeCommentary, stepsForBubble, dedupedSettledSteps } = splitLiveSteps({
    liveState,
    reasoningSteps,
    settledReasoningSteps,
    answerItemId,
  });
  const stopTaskId = turn.task?.task_id ?? null;
  const canStop = liveState.kind !== "settled" && stopTaskId !== null;
  const settledHasNothing =
    liveState.kind === "settled" && answerText === "" && dedupedSettledSteps.length === 0;

  return {
    liveState,
    activeCommentary,
    stepsForBubble,
    dedupedSettledSteps,
    answerText,
    settledHasNothing,
    canStop,
    stopTaskId,
  };
}
