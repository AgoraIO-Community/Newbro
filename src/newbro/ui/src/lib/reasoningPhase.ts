export type LiveTurnSubState = "connecting" | "reasoning" | "answering";

export type LiveTurnState =
  | { kind: "settled" }
  | { kind: "live"; sub: LiveTurnSubState };

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * State of the assistant's turn. "live" is the default; "settled" is the single
 * explicit end state, reached ONLY at a terminal turn status — not when the
 * first answer token arrives. This keeps the live cue visible while the answer
 * streams, and guarantees that no intermediate or unknown status (created,
 * queued, waiting_executor, …) can fall through to a blank render.
 */
export function deriveLiveTurnState(input: {
  status: string;     // BroTimelineTurn["status"]
  stepCount: number;  // reasoningSteps.length
  hasAnswer: boolean; // answerText !== ""
}): LiveTurnState {
  if (TERMINAL_STATUSES.has(input.status)) return { kind: "settled" };
  if (input.hasAnswer) return { kind: "live", sub: "answering" };
  if (input.stepCount > 0) return { kind: "live", sub: "reasoning" };
  return { kind: "live", sub: "connecting" };
}
