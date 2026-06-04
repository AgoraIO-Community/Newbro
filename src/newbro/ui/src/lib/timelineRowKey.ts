/**
 * Stable React list key for a timeline turn. The optimistic turn and the
 * canonical turn that replaces it share a client_request_id, so keying on it
 * lets React reuse the same DOM node across the handoff (no remount / flash).
 */
export function timelineRowKey(turn: { turn_id: string; client_request_id: string | null }): string {
  return turn.client_request_id ?? turn.turn_id;
}
