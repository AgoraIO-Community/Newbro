import { afterEach, describe, expect, it, vi } from "vitest";
import { claimDevice } from "./session-client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("claimDevice", () => {
  it("POSTs the user code to the claim endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await claimDevice("7QF2");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/devices/pair/claim");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ user_code: "7QF2" });
  });

  it("throws on a non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid pairing code." }), { status: 404 }),
    );

    await expect(claimDevice("ZZZZ")).rejects.toThrow();
  });
});
