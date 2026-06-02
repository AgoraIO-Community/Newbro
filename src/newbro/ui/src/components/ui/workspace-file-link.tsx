import { useState } from "react";
import { extractPathTokens, isUnderWorkspace, basename } from "../../lib/workspace-paths";

export const DOWNLOAD_SCHEME = "newbro-download:";

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

/** Remark plugin: split text nodes on in-workspace absolute paths and turn
 *  each into a link node with the newbro-download: scheme. */
export function remarkWorkspacePaths({ workspaceRoot }: { workspaceRoot: string }) {
  return (tree: MdNode) => {
    walk(tree, workspaceRoot);
  };
}

function walk(node: MdNode, root: string): void {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value) {
      next.push(...splitText(child.value, root));
    } else {
      if (child.type !== "link") walk(child, root); // don't descend into existing links
      next.push(child);
    }
  }
  node.children = next;
}

function splitText(value: string, root: string): MdNode[] {
  const tokens = extractPathTokens(value).filter((t) => isUnderWorkspace(t, root));
  if (tokens.length === 0) return [{ type: "text", value }];
  const out: MdNode[] = [];
  let rest = value;
  // Process longest tokens first so a token that is a prefix of another wins on
  // an equal-position tie.
  const ordered = [...tokens].sort((a, b) => b.length - a.length);
  // Repeatedly find the earliest token occurrence, emitting text + link nodes.
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let bestIdx = -1;
    let bestTok = "";
    for (const tok of ordered) {
      const i = rest.indexOf(tok);
      if (i !== -1 && (bestIdx === -1 || i < bestIdx)) {
        bestIdx = i;
        bestTok = tok;
      }
    }
    if (bestIdx === -1) {
      if (rest) out.push({ type: "text", value: rest });
      break;
    }
    if (bestIdx > 0) out.push({ type: "text", value: rest.slice(0, bestIdx) });
    out.push({
      type: "link",
      url: `${DOWNLOAD_SCHEME}${bestTok}`,
      children: [{ type: "text", value: bestTok }],
    });
    rest = rest.slice(bestIdx + bestTok.length);
  }
  return out;
}

/** The clickable Download control rendered for newbro-download: links. */
export function WorkspaceFileLink({
  path,
  downloadUrl,
}: {
  path: string;
  downloadUrl: (path: string) => string;
}) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const name = basename(path);

  async function onClick(event: React.MouseEvent) {
    event.preventDefault();
    if (state === "loading") return;
    setState("loading");
    try {
      const response = await fetch(downloadUrl(path), { credentials: "include" });
      if (!response.ok) {
        setState("error");
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <a
      href={downloadUrl(path)}
      onClick={onClick}
      className="break-words text-primary underline decoration-primary/35 underline-offset-2"
      data-testid="workspace-file-download"
    >
      ↓ {name}
      {state === "loading" ? " …" : ""}
      {state === "error" ? " (download failed)" : ""}
    </a>
  );
}
