import { describe, it, expect } from "vitest";
import { splitLiveSteps } from "./splitLiveSteps";
import type { ReasoningStep } from "../components/newbro/adapters";

function step(id: string, label: string, status: "active" | "done" = "done"): ReasoningStep {
  return { id, label, status, created_at: id };
}

const reasoning = [
  step("s1", "Reading the repo", "done"),
  step("s2", "Drafting the report", "active"),
];

describe("splitLiveSteps (codex multi-message turn contract)", () => {
  it("reasoning: the latest step is the prominent commentary and is excluded from the compact steps", () => {
    const { activeCommentary, stepsForBubble } = splitLiveSteps({
      liveState: { kind: "live", sub: "reasoning" },
      reasoningSteps: reasoning,
      settledReasoningSteps: [],
      answerItemId: null,
    });
    expect(activeCommentary).toBe("Drafting the report");
    expect(stepsForBubble.map((s) => s.id)).toEqual(["s1"]);
    // No duplication: the active commentary label is not also a compact step.
    expect(stepsForBubble.map((s) => s.label)).not.toContain("Drafting the report");
  });

  it("answering: no commentary line; all steps render compactly", () => {
    const { activeCommentary, stepsForBubble } = splitLiveSteps({
      liveState: { kind: "live", sub: "answering" },
      reasoningSteps: reasoning,
      settledReasoningSteps: [],
      answerItemId: null,
    });
    expect(activeCommentary).toBeNull();
    expect(stepsForBubble.map((s) => s.id)).toEqual(["s1", "s2"]);
  });

  it("connecting: no commentary line and no crash on empty steps", () => {
    const { activeCommentary, stepsForBubble } = splitLiveSteps({
      liveState: { kind: "live", sub: "connecting" },
      reasoningSteps: [],
      settledReasoningSteps: [],
      answerItemId: null,
    });
    expect(activeCommentary).toBeNull();
    expect(stepsForBubble).toEqual([]);
  });

  it("settled: steps are the deduped settled list with the final-answer step removed", () => {
    const settled = [step("s1", "Reading the repo"), step("answer-1", "The full report")];
    const { activeCommentary, stepsForBubble, dedupedSettledSteps } = splitLiveSteps({
      liveState: { kind: "settled" },
      reasoningSteps: [],
      settledReasoningSteps: settled,
      answerItemId: "answer-1",
    });
    expect(activeCommentary).toBeNull();
    expect(stepsForBubble.map((s) => s.id)).toEqual(["s1"]);
    expect(dedupedSettledSteps.map((s) => s.id)).toEqual(["s1"]);
  });
});
