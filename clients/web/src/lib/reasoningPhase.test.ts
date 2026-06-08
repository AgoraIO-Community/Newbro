import { describe, it, expect } from "vitest";
import { deriveLiveTurnState } from "./reasoningPhase";

describe("deriveLiveTurnState", () => {
  it("terminal statuses settle", () => {
    for (const status of ["completed", "failed", "cancelled"]) {
      expect(deriveLiveTurnState({ status, stepCount: 0, hasAnswer: false })).toEqual({ kind: "settled" });
    }
  });

  it("a settled turn stays settled even with steps and an answer", () => {
    expect(deriveLiveTurnState({ status: "completed", stepCount: 3, hasAnswer: true })).toEqual({ kind: "settled" });
  });

  it("optimistic/pending with nothing yet is live:connecting", () => {
    expect(deriveLiveTurnState({ status: "pending", stepCount: 0, hasAnswer: false })).toEqual({ kind: "live", sub: "connecting" });
  });

  it("every non-terminal status stays live (never blank) during executor spin-up", () => {
    for (const status of ["created", "queued", "waiting_executor", "running", "anything-unexpected"]) {
      expect(deriveLiveTurnState({ status, stepCount: 0, hasAnswer: false })).toEqual({ kind: "live", sub: "connecting" });
    }
  });

  it("steps but no answer is live:reasoning", () => {
    expect(deriveLiveTurnState({ status: "running", stepCount: 2, hasAnswer: false })).toEqual({ kind: "live", sub: "reasoning" });
  });

  it("an answer while still non-terminal is live:answering (cue must stay)", () => {
    expect(deriveLiveTurnState({ status: "running", stepCount: 2, hasAnswer: true })).toEqual({ kind: "live", sub: "answering" });
  });
});
