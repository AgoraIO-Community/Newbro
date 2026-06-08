import { useEffect, useRef, useState } from "react";
import { readThreadIdFromUrl, replaceThreadIdInUrl } from "./session-url";

const NEW_THREAD_SENTINEL = "new";

export interface UseThreadSelectionParams<T extends { threadId: string }> {
  broId: string | null;
  broSource: string | null;
  threads: T[];
  workspaceOptions: unknown[];
  needsConnect: boolean;
  openThread: (broId: string, threadId: string) => void;
  closeThread: (broId: string, threadId: string | null) => void;
  onNoWorkspace: () => void;
}

export interface UseThreadSelectionResult<T> {
  selectedThreadId: string | null;
  pendingNewThread: boolean;
  pendingWorkspaceId: string | null;
  workspacePickerOpen: boolean;
  setWorkspacePickerOpen: (open: boolean) => void;
  selectedThread: T | null;
  activeThreadId: string | null;
  selectThread: (threadId: string) => void;
  newThread: () => void;
  selectWorkspace: (workspaceId: string) => void;
  resolveThread: (threadId: string | null) => void;
}

export function useThreadSelection<T extends { threadId: string }>(
  params: UseThreadSelectionParams<T>,
): UseThreadSelectionResult<T> {
  const { broId, broSource, threads, workspaceOptions, needsConnect, openThread, closeThread, onNoWorkspace } = params;

  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => {
    const initial = readThreadIdFromUrl();
    return initial === NEW_THREAD_SENTINEL ? null : initial;
  });
  const [pendingNewThread, setPendingNewThread] = useState(() => readThreadIdFromUrl() === NEW_THREAD_SENTINEL);
  const [pendingWorkspaceId, setPendingWorkspaceId] = useState<string | null>(null);
  const [workspacePickerOpen, setWorkspacePickerOpen] = useState(false);
  const openedThreadRef = useRef<string | null>(null);
  const activeThreadRef = useRef<string | null>(null);
  // Hold the latest open/close callbacks in refs so the open/unmount effects
  // don't list them as deps — callers pass inline closures, and a changing
  // identity would otherwise re-run the open effect every render and (worse)
  // fire the unmount cleanup early, closing the live thread prematurely.
  const openThreadRef = useRef(openThread);
  const closeThreadRef = useRef(closeThread);
  useEffect(() => {
    openThreadRef.current = openThread;
    closeThreadRef.current = closeThread;
  });

  const matchedThread = threads.find((thread) => thread.threadId === selectedThreadId) ?? null;
  const selectedThread = pendingNewThread ? null : matchedThread;
  // Keep the id even while the matching record hasn't loaded yet, so a
  // just-resolved new thread's optimistic turns still belong to it.
  const activeThreadId = pendingNewThread ? null : selectedThreadId;

  // Auto-select the latest thread ONLY when there is no selection intent at all.
  useEffect(() => {
    if (pendingNewThread || selectedThreadId !== null || threads.length === 0) return;
    setSelectedThreadId(threads[0].threadId);
    replaceThreadIdInUrl(threads[0].threadId);
  }, [pendingNewThread, selectedThreadId, threads]);

  // Open the active thread server-side (skip a just-resolved/just-opened one).
  useEffect(() => {
    if (pendingNewThread || needsConnect || !broId || broSource !== "runtime" || !activeThreadId) return;
    if (openedThreadRef.current === activeThreadId) return;
    openedThreadRef.current = activeThreadId;
    openThreadRef.current(broId, activeThreadId);
  }, [activeThreadId, broId, broSource, needsConnect, pendingNewThread]);

  useEffect(() => {
    activeThreadRef.current = activeThreadId;
  }, [activeThreadId]);

  useEffect(() => {
    return () => {
      if (broSource === "runtime" && broId) {
        closeThreadRef.current(broId, activeThreadRef.current);
      }
    };
  }, [broId, broSource]);

  function selectThread(threadId: string) {
    // No close on switch: the new thread's subscribe POST replaces the previous
    // subscription server-side. The old thread's cached timeline can stay.
    setPendingNewThread(false);
    setPendingWorkspaceId(null);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = null;
  }

  function newThread() {
    if (workspaceOptions.length === 0) {
      onNoWorkspace();
      return;
    }
    setWorkspacePickerOpen(true);
  }

  function selectWorkspace(workspaceId: string) {
    setPendingNewThread(true);
    setPendingWorkspaceId(workspaceId);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(null);
    replaceThreadIdInUrl(NEW_THREAD_SENTINEL);
  }

  function resolveThread(threadId: string | null) {
    if (!threadId) return;
    setPendingNewThread(false);
    setPendingWorkspaceId(null);
    setWorkspacePickerOpen(false);
    setSelectedThreadId(threadId);
    replaceThreadIdInUrl(threadId);
    openedThreadRef.current = threadId;
  }

  return {
    selectedThreadId,
    pendingNewThread,
    pendingWorkspaceId,
    workspacePickerOpen,
    setWorkspacePickerOpen,
    selectedThread,
    activeThreadId,
    selectThread,
    newThread,
    selectWorkspace,
    resolveThread,
  };
}
