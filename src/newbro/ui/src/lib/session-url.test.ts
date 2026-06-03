import { describe, it, expect, beforeEach } from "vitest";
import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./session-url";

describe("session-url thread param", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("passes the 'new' sentinel through unchanged", () => {
    window.history.replaceState({}, "", "/?thread=new");
    expect(readThreadIdFromUrl()).toBe("new");
  });
  it("round-trips an id and clears on null", () => {
    replaceThreadIdInUrl("t-123");
    expect(readThreadIdFromUrl()).toBe("t-123");
    replaceThreadIdInUrl(null);
    expect(readThreadIdFromUrl()).toBeNull();
  });
});
