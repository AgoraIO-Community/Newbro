const LEADING = /^[(<"'`[]+/;
const TRAILING = /[.,;:!?)\]}>"'`]+$/;

/** Absolute-path tokens in `text`, mirroring the backend grammar. */
export function extractPathTokens(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/\s+/)) {
    const token = raw.replace(LEADING, "").replace(TRAILING, "");
    if (!token || token.includes("\0") || !token.startsWith("/")) continue;
    if (!seen.has(token)) {
      seen.add(token);
      out.push(token);
    }
  }
  return out;
}

export function isUnderWorkspace(path: string, root: string): boolean {
  const r = root.replace(/\/+$/, "");
  return path === r || path.startsWith(`${r}/`);
}

export function basename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}
