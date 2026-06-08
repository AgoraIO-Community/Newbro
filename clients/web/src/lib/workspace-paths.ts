// Mirror of the backend grammar (newbro/api/workspace_path_tokens.py): an
// absolute-path token begins at a boundary (start, whitespace, or an opening
// bracket/brace/angle/quote/backtick — so markdown-link targets `](/abs/path)`,
// parentheses, quotes, and backticks are detected), starts with `/`, and runs
// until whitespace or a closing bracket/brace/angle/quote/backtick. Relative
// paths (`out/x`) and URLs (`https://...`) are not matched.
const PATH_TOKEN_RE = /(?:^|(?<=[\s(\[{<"'`]))(\/[^\s()[\]{}<>"'`]*)/g;
const TRAILING = /[.,;:!?]+$/;

/** Absolute-path tokens in `text`, mirroring the backend grammar. */
export function extractPathTokens(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const match of text.matchAll(PATH_TOKEN_RE)) {
    const token = match[1].replace(TRAILING, "");
    if (!token || token.includes("\0")) continue;
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
