import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useThreadSelection } from "./useThreadSelection";

interface T { threadId: string; title?: string }

function setUrl(search: string) {
  window.history.replaceState({}, "", search ? `/?${search}` : "/");
}
function threadParam(): string | null {
  return new URLSearchParams(window.location.search).get("thread");
}
function defaults(over: Partial<Parameters<typeof useThreadSelection<T>>[0]> = {}) {
  return {
    broId: "bro-1",
    broSource: "runtime",
    threads: [] as T[],
    workspaceOptions: ["ws-1"],
    needsConnect: false,
    openThread: vi.fn(),
    closeThread: vi.fn(),
    onNoWorkspace: vi.fn(),
    ...over,
  };
}

describe("useThreadSelection", () => {
  beforeEach(() => setUrl(""));

  it("?thread=new seeds pendingNewThread and never auto-selects, even with threads", () => {
    setUrl("thread=new");
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    expect(result.current.pendingNewThread).toBe(true);
    expect(result.current.selectedThreadId).toBeNull();
    expect(result.current.activeThreadId).toBeNull();
    expect(threadParam()).toBe("new");
  });

  it("no thread param + threads present → auto-selects threads[0] and writes the url", () => {
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    expect(result.current.selectedThreadId).toBe("a");
    expect(threadParam()).toBe("a");
  });

  it("selectWorkspace enters new-thread mode and marks the url", () => {
    const { result } = renderHook(() => useThreadSelection<T>(defaults()));
    act(() => result.current.selectWorkspace("ws-1"));
    expect(result.current.pendingNewThread).toBe(true);
    expect(result.current.selectedThreadId).toBeNull();
    expect(threadParam()).toBe("new");
  });

  it("resolveThread to an id not yet in threads → activeThreadId is that id, selectedThread null (no threads[0])", () => {
    const threads: T[] = [{ threadId: "a" }];
    setUrl("thread=new");
    const { result, rerender } = renderHook(
      (props: { threads: T[] }) => useThreadSelection<T>(defaults({ threads: props.threads })),
      { initialProps: { threads } },
    );
    act(() => result.current.resolveThread("newId"));
    expect(result.current.pendingNewThread).toBe(false);
    expect(result.current.selectedThreadId).toBe("newId");
    expect(result.current.activeThreadId).toBe("newId");
    expect(result.current.selectedThread).toBeNull();
    expect(threadParam()).toBe("newId");
    rerender({ threads: [{ threadId: "a" }, { threadId: "newId", title: "New" }] });
    expect(result.current.selectedThread?.threadId).toBe("newId");
  });

  it("selectThread selects an existing thread and writes the url", () => {
    const threads: T[] = [{ threadId: "a" }, { threadId: "b" }];
    setUrl("thread=a");
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ threads })));
    act(() => result.current.selectThread("b"));
    expect(result.current.selectedThreadId).toBe("b");
    expect(result.current.selectedThread?.threadId).toBe("b");
    expect(threadParam()).toBe("b");
  });

  it("newThread with no workspaces calls onNoWorkspace and does not open the picker", () => {
    const onNoWorkspace = vi.fn();
    const { result } = renderHook(() => useThreadSelection<T>(defaults({ workspaceOptions: [], onNoWorkspace })));
    act(() => result.current.newThread());
    expect(onNoWorkspace).toHaveBeenCalledTimes(1);
    expect(result.current.workspacePickerOpen).toBe(false);
  });

  it("opens the active thread once; a re-render does not re-open it", () => {
    const openThread = vi.fn();
    setUrl("thread=a");
    const threads: T[] = [{ threadId: "a" }];
    const { rerender } = renderHook(() => useThreadSelection<T>(defaults({ threads, openThread })));
    expect(openThread).toHaveBeenCalledWith("bro-1", "a");
    expect(openThread).toHaveBeenCalledTimes(1);
    rerender();
    expect(openThread).toHaveBeenCalledTimes(1);
  });

  it("does not close the live thread on re-render when the caller passes a fresh closure", () => {
    // Regression: closeThread must NOT be an effect dep, or the unmount cleanup
    // fires every render (the caller passes an inline closure each time).
    const realClose = vi.fn();
    setUrl("thread=a");
    const threads: T[] = [{ threadId: "a" }];
    const { rerender, unmount } = renderHook(() =>
      useThreadSelection<T>(defaults({ threads, closeThread: (id, tid) => realClose(id, tid) })),
    );
    rerender();
    rerender();
    expect(realClose).not.toHaveBeenCalled();
    unmount();
    expect(realClose).toHaveBeenCalledTimes(1);
  });
});
