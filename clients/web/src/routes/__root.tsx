/// <reference types="vite/client" />
import { HeadContent, Outlet, createRootRoute } from "@tanstack/react-router";
import type { DetailedHTMLProps, LinkHTMLAttributes } from "react";
import { normalizeSessionIdParam, normalizeThreadIdParam } from "../lib/session-url";
import { NewbroShellProvider } from "../NewbroShell";

const externalFontLinks: Array<
  DetailedHTMLProps<LinkHTMLAttributes<HTMLLinkElement>, HTMLLinkElement>
> =
  import.meta.env.MODE === "test"
    ? []
    : [
        {
          rel: "stylesheet",
          href:
            "https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;600;700&family=Noto+Sans+SC:wght@400;700&display=swap",
        },
      ];

export const Route = createRootRoute({
  validateSearch: (search: Record<string, unknown>) => {
    const sid = normalizeSessionIdParam(search.sid);
    const thread = normalizeThreadIdParam(search.thread);
    return { ...(sid ? { sid } : {}), ...(thread ? { thread } : {}) };
  },
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Newbro Voice Writing Desk" },
      {
        name: "description",
        content:
          "A calm voice-first writing desk for the Newbro frontend shell.",
      },
    ],
    links: externalFontLinks,
  }),
  component: RootDocument,
  errorComponent: () => null,
  notFoundComponent: () => null,
});

function RootDocument() {
  return (
    <>
      <HeadContent />
      <NewbroShellProvider>
        <Outlet />
      </NewbroShellProvider>
    </>
  );
}
