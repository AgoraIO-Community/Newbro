import { useMemo } from "react";
import ReactMarkdown, { type Components, type UrlTransform } from "react-markdown";
import type { Pluggable } from "unified";
import remarkGfm from "remark-gfm";
import { cn } from "../../lib/utils";
import { buildHttpUrl, API_PREFIX } from "../../lib/session-client";
import {
  DOWNLOAD_SCHEME,
  WorkspaceFileLink,
  remarkWorkspacePaths,
} from "./workspace-file-link";

const SAFE_PROTOCOL = /^(https?|ircs?|mailto|xmpp)$/i;

function makeUrlTransform(hasDownload: boolean): UrlTransform {
  return (value: string) => {
    if (hasDownload && value.startsWith(DOWNLOAD_SCHEME)) return value;
    const colon = value.indexOf(":");
    const questionMark = value.indexOf("?");
    const numberSign = value.indexOf("#");
    const slash = value.indexOf("/");
    if (
      colon === -1 ||
      (slash !== -1 && colon > slash) ||
      (questionMark !== -1 && colon > questionMark) ||
      (numberSign !== -1 && colon > numberSign) ||
      SAFE_PROTOCOL.test(value.slice(0, colon))
    ) {
      return value;
    }
    return "";
  };
}

export interface MarkdownDownloadContext {
  sessionId: string;
  threadId: string;
  turnId: string;
  workspaceRoot: string;
}

function baseComponents(downloadUrl: ((path: string) => string) | null): Components {
  return {
    a({ node, href, children, ...props }) {
      if (downloadUrl && typeof href === "string" && href.startsWith(DOWNLOAD_SCHEME)) {
        const path = href.slice(DOWNLOAD_SCHEME.length);
        return <WorkspaceFileLink path={path} downloadUrl={downloadUrl} />;
      }
      return (
        <a
          {...props}
          href={href}
          className={cn(
            "break-words text-primary underline decoration-primary/35 underline-offset-2",
            (props as { className?: string }).className,
          )}
          rel="noreferrer"
          target="_blank"
        >
          {children}
        </a>
      );
    },
    code({ node, ...props }) {
      return (
        <code
          {...props}
          className={cn(
            "rounded bg-muted/75 px-1 py-0.5 font-mono text-[0.92em] text-foreground break-words",
            props.className,
          )}
        />
      );
    },
    pre({ node, ...props }) {
      return (
        <pre
          {...props}
          className={cn(
            "my-2 max-w-full overflow-x-auto rounded-md bg-muted/75 p-2 font-mono text-[11px] leading-5 text-foreground",
            props.className,
          )}
        />
      );
    },
    p({ node, ...props }) {
      return <p {...props} className={cn("my-2 break-words", props.className)} />;
    },
    ul({ node, ...props }) {
      return <ul {...props} className={cn("my-2 list-disc space-y-1 pl-5", props.className)} />;
    },
    ol({ node, ...props }) {
      return <ol {...props} className={cn("my-2 list-decimal space-y-1 pl-5", props.className)} />;
    },
    li({ node, ...props }) {
      return <li {...props} className={cn("pl-0.5", props.className)} />;
    },
    blockquote({ node, ...props }) {
      return (
        <blockquote
          {...props}
          className={cn("my-2 border-l-2 border-border pl-3 text-muted-foreground", props.className)}
        />
      );
    },
    table({ node, ...props }) {
      return (
        <table
          {...props}
          className={cn("my-2 block max-w-full overflow-x-auto border-collapse text-left text-[0.95em]", props.className)}
        />
      );
    },
    th({ node, ...props }) {
      return <th {...props} className={cn("border border-border px-2 py-1 font-medium", props.className)} />;
    },
    td({ node, ...props }) {
      return <td {...props} className={cn("border border-border px-2 py-1 align-top", props.className)} />;
    },
  };
}

export function MarkdownText({
  children,
  className,
  downloadContext,
}: {
  children: string;
  className?: string;
  downloadContext?: MarkdownDownloadContext;
}) {
  const { sessionId, threadId, turnId, workspaceRoot } = downloadContext ?? {};

  const downloadUrl = useMemo<((path: string) => string) | null>(() => {
    if (!sessionId || !threadId || !turnId || !workspaceRoot) return null;
    return (path: string) =>
      buildHttpUrl(
        `${API_PREFIX}/sessions/${sessionId}/bro-threads/${encodeURIComponent(
          threadId,
        )}/turns/${encodeURIComponent(turnId)}/file?path=${encodeURIComponent(path)}`,
      );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, threadId, turnId, workspaceRoot]);

  const remarkPlugins = useMemo<Pluggable[]>(
    () =>
      workspaceRoot
        ? [remarkGfm, [remarkWorkspacePaths, { workspaceRoot }] as Pluggable]
        : [remarkGfm],
    [workspaceRoot],
  );

  const components = useMemo(() => baseComponents(downloadUrl), [downloadUrl]);

  const urlTransform = useMemo(() => makeUrlTransform(downloadUrl !== null), [downloadUrl]);

  return (
    <div className={cn("min-w-0 max-w-full overflow-hidden [&>:first-child]:mt-0 [&>:last-child]:mb-0", className)}>
      <ReactMarkdown
        disallowedElements={["img"]}
        remarkPlugins={remarkPlugins}
        urlTransform={urlTransform}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
