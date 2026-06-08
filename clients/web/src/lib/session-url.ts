export function normalizeSessionIdParam(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

export function normalizeThreadIdParam(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

export function readSessionIdFromUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return normalizeSessionIdParam(new URLSearchParams(window.location.search).get("sid")) ?? null;
}

export function replaceSessionIdInUrl(sessionId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }

  const url = new URL(window.location.href);
  const normalized = normalizeSessionIdParam(sessionId);
  if (normalized) {
    url.searchParams.set("sid", normalized);
  } else {
    url.searchParams.delete("sid");
  }

  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) {
    return;
  }

  window.history.replaceState(window.history.state, "", next);
}

export function readThreadIdFromUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return normalizeThreadIdParam(new URLSearchParams(window.location.search).get("thread")) ?? null;
}

export function replaceThreadIdInUrl(threadId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }

  const url = new URL(window.location.href);
  const normalized = normalizeThreadIdParam(threadId);
  if (normalized) {
    url.searchParams.set("thread", normalized);
  } else {
    url.searchParams.delete("thread");
  }

  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) {
    return;
  }

  window.history.replaceState(window.history.state, "", next);
}
