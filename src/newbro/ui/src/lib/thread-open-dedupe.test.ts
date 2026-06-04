import { describe, expect, it } from "vitest";
import { beginThreadOpen, finishThreadOpen, threadOpenKey } from "./thread-open-dedupe";

describe("thread-open-dedupe", () => {
  it("builds stable collision-resistant keys", () => {
    expect(threadOpenKey("forge", "thread-1")).toBe(threadOpenKey("forge", "thread-1"));
    expect(threadOpenKey("forge", "thread-1")).not.toBe(threadOpenKey("forge", "thread-2"));
    expect(threadOpenKey("for:ge", "thread:1")).not.toBe(threadOpenKey("for", "ge:thread:1"));
    expect(threadOpenKey("a", "\u0000b")).not.toBe(threadOpenKey("a\u0000", "b"));
  });

  it("allows the first open and rejects duplicates until finished", () => {
    const inFlight = new Set<string>();

    const first = beginThreadOpen(inFlight, "forge", "thread-1");
    const duplicate = beginThreadOpen(inFlight, "forge", "thread-1");
    const otherThread = beginThreadOpen(inFlight, "forge", "thread-2");

    expect(first).toBe(threadOpenKey("forge", "thread-1"));
    expect(duplicate).toBeNull();
    expect(otherThread).toBe(threadOpenKey("forge", "thread-2"));

    finishThreadOpen(inFlight, first);
    expect(beginThreadOpen(inFlight, "forge", "thread-1")).toBe(threadOpenKey("forge", "thread-1"));
  });
});
