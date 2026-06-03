import { describe, it, expect } from "vitest";
import { deriveReasoningPhase } from "./reasoningPhase";

describe("deriveReasoningPhase", () => {
  it("pending with no steps → ack (the just-sent optimistic turn)", () => {
    expect(deriveReasoningPhase({ status: "pending", stepCount: 0, hasAnswer: false })).toBe("ack");
  });
  it("running with no steps → ack", () => {
    expect(deriveReasoningPhase({ status: "running", stepCount: 0, hasAnswer: false })).toBe("ack");
  });
  it("running with steps → streaming", () => {
    expect(deriveReasoningPhase({ status: "running", stepCount: 3, hasAnswer: false })).toBe("streaming");
  });
  it("pending but answer already present → done", () => {
    expect(deriveReasoningPhase({ status: "pending", stepCount: 0, hasAnswer: true })).toBe("done");
  });
  it("completed → done", () => {
    expect(deriveReasoningPhase({ status: "completed", stepCount: 5, hasAnswer: true })).toBe("done");
  });
  it("failed → done", () => {
    expect(deriveReasoningPhase({ status: "failed", stepCount: 0, hasAnswer: false })).toBe("done");
  });
  it("cancelled → done", () => {
    expect(deriveReasoningPhase({ status: "cancelled", stepCount: 2, hasAnswer: false })).toBe("done");
  });
});
