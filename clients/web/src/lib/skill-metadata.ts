/**
 * Reads the `skill` field from a persisted message or turn metadata object.
 * Task 14 writes `metadata.skill = { name, display_name }` on the backend.
 */
export function skillFromMessageMetadata(
  metadata: Record<string, unknown> | undefined,
): { name: string; display_name: string } | null {
  const skill = metadata?.skill;
  if (skill && typeof skill === "object" && !Array.isArray(skill) && "name" in skill) {
    const s = skill as { name: string; display_name?: string };
    if (typeof s.name !== "string" || !s.name) return null;
    return { name: s.name, display_name: s.display_name ?? s.name };
  }
  return null;
}
