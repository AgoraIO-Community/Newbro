export type ReasoningPhase = "ack" | "streaming" | "done";

/**
 * Phase of the assistant's live turn. In-flight is keyed off the TURN STATUS
 * (not activeRun/steps) so the optimistic `pending` turn shown the instant a
 * message is sent resolves to `ack` and the skeleton appears immediately.
 */
export function deriveReasoningPhase(input: {
  status: string;       // BroTimelineTurn["status"]
  stepCount: number;    // reasoningSteps.length
  hasAnswer: boolean;   // answerText !== ""
}): ReasoningPhase {
  const inFlight = (input.status === "pending" || input.status === "running") && !input.hasAnswer;
  if (!inFlight) return "done";
  return input.stepCount > 0 ? "streaming" : "ack";
}
