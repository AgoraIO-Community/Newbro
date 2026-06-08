import { describe, it, expect } from "vitest";
import { timelineRowKey } from "./timelineRowKey";

describe("timelineRowKey", () => {
  it("uses client_request_id so optimistic and canonical turns share a key", () => {
    const optimistic = { turn_id: "optimistic:abc", client_request_id: "abc" };
    const canonical = { turn_id: "turn-real-123", client_request_id: "abc" };
    expect(timelineRowKey(optimistic)).toBe("abc");
    expect(timelineRowKey(canonical)).toBe(timelineRowKey(optimistic));
  });

  it("falls back to turn_id when there is no client_request_id", () => {
    expect(timelineRowKey({ turn_id: "turn-real-123", client_request_id: null })).toBe("turn-real-123");
  });
});
