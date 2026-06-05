import type { ReasoningStep } from "../components/newbro/adapters";
import type { LiveTurnState } from "./reasoningPhase";

export interface LiveStepsSplit {
  /** The currently-streaming commentary line, shown prominently above the
   * compact step list while reasoning; null otherwise. */
  activeCommentary: string | null;
  /** Steps to render in the compact list: while reasoning the active step is
   * pulled out (shown as `activeCommentary`); when settled the answer step is
   * de-duplicated out. */
  stepsForBubble: ReasoningStep[];
  /** Settled steps with the final-answer step removed (kept for callers that
   * need it, e.g. an "empty settled turn" check). */
  dedupedSettledSteps: ReasoningStep[];
}

/**
 * Split native reasoning steps into the prominent streaming "commentary" line
 * and the compact step list, per the codex multi-message turn contract:
 *
 * - While reasoning, the latest step is the streaming commentary (prominent)
 *   and is excluded from the compact list.
 * - While answering, there is no separate commentary line — all steps render
 *   compactly and the answer is shown prominently.
 * - When settled, steps render as the deduped (collapsible) list and the answer
 *   is the settled answer.
 *
 * Pure and side-effect free so it can be unit tested without React context.
 */
export function splitLiveSteps(input: {
  liveState: LiveTurnState;
  reasoningSteps: ReasoningStep[];
  settledReasoningSteps: ReasoningStep[];
  answerItemId: string | null;
}): LiveStepsSplit {
  const { liveState, reasoningSteps, settledReasoningSteps, answerItemId } = input;

  const dedupedSettledSteps = answerItemId
    ? settledReasoningSteps.filter((step) => step.id !== answerItemId)
    : settledReasoningSteps;

  const isReasoning = liveState.kind === "live" && liveState.sub === "reasoning";
  const activeCommentary =
    isReasoning && reasoningSteps.length > 0 ? reasoningSteps[reasoningSteps.length - 1].label : null;

  const stepsForBubble =
    liveState.kind === "settled"
      ? dedupedSettledSteps
      : isReasoning
        ? reasoningSteps.slice(0, -1)
        : reasoningSteps;

  return { activeCommentary, stepsForBubble, dedupedSettledSteps };
}
