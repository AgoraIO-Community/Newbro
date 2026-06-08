import { describe, it, expect } from "vitest";
import { buildExecutorTextPayload } from "../../ArtboardShell";

describe("buildExecutorTextPayload", () => {
  const base = {
    targetPersonaId: "persona-1",
    targetThreadId: "thread-1",
    createNewThread: false,
    workspaceId: null,
    clientRequestId: "turn-abc",
    planMode: false,
    skill: null,
    text: "hello",
  };

  it("includes skillName when skill is provided", () => {
    const result = buildExecutorTextPayload({ ...base, skill: { name: "doc" } });
    expect(result.skillName).toBe("doc");
  });

  it("does NOT include skillName when skill is null", () => {
    const result = buildExecutorTextPayload({ ...base, skill: null });
    expect(Object.prototype.hasOwnProperty.call(result, "skillName")).toBe(false);
  });

  it("includes planMode: true when planMode is true", () => {
    const result = buildExecutorTextPayload({ ...base, planMode: true });
    expect(result.planMode).toBe(true);
  });

  it("does NOT include planMode when planMode is false", () => {
    const result = buildExecutorTextPayload({ ...base, planMode: false });
    expect(Object.prototype.hasOwnProperty.call(result, "planMode")).toBe(false);
  });

  it("includes workspaceId when provided", () => {
    const result = buildExecutorTextPayload({ ...base, workspaceId: "ws-42" });
    expect(result.workspaceId).toBe("ws-42");
  });

  it("does NOT include workspaceId when null", () => {
    const result = buildExecutorTextPayload({ ...base, workspaceId: null });
    expect(Object.prototype.hasOwnProperty.call(result, "workspaceId")).toBe(false);
  });

  it("always includes core fields", () => {
    const result = buildExecutorTextPayload(base);
    expect(result.targetPersonaId).toBe("persona-1");
    expect(result.targetThreadId).toBe("thread-1");
    expect(result.createNewThread).toBe(false);
    expect(result.clientRequestId).toBe("turn-abc");
    expect(result.text).toBe("hello");
  });
});
