export function threadOpenKey(targetPersonaId: string, threadId: string): string {
  return JSON.stringify([targetPersonaId, threadId]);
}

export function beginThreadOpen(
  inFlight: Set<string>,
  targetPersonaId: string,
  threadId: string,
): string | null {
  const key = threadOpenKey(targetPersonaId, threadId);
  if (inFlight.has(key)) {
    return null;
  }
  inFlight.add(key);
  return key;
}

export function finishThreadOpen(inFlight: Set<string>, key: string | null): void {
  if (key !== null) {
    inFlight.delete(key);
  }
}
